from __future__ import annotations

import re

from src.models import (
    ChunkSummary,
    DraftParagraphLabel,
    FirstPassResult,
    LowValueSegment,
    StructuredSummary,
    TemplateDefinition,
    TemplateResult,
    TemplateSection,
    TranscriptBundle,
    TranscriptChunk,
    TranscriptResult,
)
from src.utils import dedupe_keep_order, format_timestamp, has_timeline, normalize_whitespace


FILLER_KEYWORDS = (
    "点赞",
    "关注",
    "转发",
    "评论区",
    "兄弟们",
    "姐妹们",
    "今天这个视频",
    "先别划走",
    "废话不多说",
    "广告",
)


class FallbackSummarizer:
    provider = "fallback"
    model = "rule-based"

    def run_first_pass(self, transcript_result: TranscriptBundle | TranscriptResult) -> FirstPassResult:
        paragraphs = [normalize_whitespace(chunk.text) for chunk in transcript_result.chunks if normalize_whitespace(chunk.text)]
        if not paragraphs and transcript_result.transcript_text:
            paragraphs = [normalize_whitespace(transcript_result.transcript_text)]

        cleaned_transcript = "\n\n".join(paragraphs)
        candidate_points = self._extract_candidate_points(transcript_result)
        high_value_points = candidate_points[:6]
        value_rating = self._infer_value_rating(high_value_points, cleaned_transcript)
        value_reason = self._build_value_reason(value_rating, high_value_points, cleaned_transcript)
        headline_verdict = self._build_headline_verdict(value_rating, high_value_points)
        one_line_verdict = self._build_one_line_verdict(value_rating, high_value_points)
        objective_context = self._build_objective_context(high_value_points)
        low_value_segments = self._build_low_value_segments(transcript_result)
        draft_paragraphs = self._build_draft_paragraphs(paragraphs, low_value_segments)
        generated_title = self._build_generated_title(transcript_result, high_value_points, value_rating)

        warning = (
            "未配置或未成功调用远程总结模型，当前使用本地规则生成首轮底稿。"
            " 结构可用，但质量会明显弱于大模型结果。"
        )
        return FirstPassResult(
            provider=self.provider,
            model=self.model,
            cleaned_transcript=cleaned_transcript or transcript_result.transcript_text,
            one_line_verdict=one_line_verdict,
            headline_verdict=headline_verdict,
            value_rating=value_rating,
            value_reason=value_reason,
            high_value_points=high_value_points,
            objective_context=objective_context,
            low_value_segments=low_value_segments,
            raw_transcript_reference=transcript_result.transcript_text,
            draft_paragraphs=draft_paragraphs,
            uncertainty_notes=[],
            needs_human_check_timestamps=[],
            generated_title=generated_title,
            warning=warning,
        )

    def run_template_pass(
        self,
        first_pass: FirstPassResult,
        template_definition: TemplateDefinition,
    ) -> TemplateResult:
        template_id = template_definition.id
        sections = self._build_template_sections(first_pass, template_id)
        overview = self._build_template_overview(first_pass, template_id)
        key_points = self._build_template_key_points(first_pass, template_id)
        fields = self._build_template_fields(first_pass, template_id)
        warning = (
            "当前模板结果来自本地规则 fallback。"
            " 适合作为结构占位和回退结果，不代表最终质量上限。"
        )
        return TemplateResult(
            template_id=template_definition.id,
            template_name=template_definition.name,
            provider=self.provider,
            model=self.model,
            overview=overview,
            key_points=key_points,
            section_summaries=sections,
            template_fields=fields,
            warning=warning,
            template_source=template_definition.source,
            template_version=template_definition.version,
        )

    def summarize(self, transcript_result: TranscriptBundle | TranscriptResult, style: str) -> StructuredSummary:
        chunk_summaries = [self._summarize_chunk(chunk) for chunk in transcript_result.chunks]
        first_pass = self.run_first_pass(transcript_result)
        template_name = style.strip() or "简洁总结"
        return StructuredSummary(
            provider=self.provider,
            model=self.model,
            overall_summary=first_pass.headline_verdict,
            key_points=first_pass.high_value_points[:10],
            action_items=self._extract_action_items(first_pass.cleaned_transcript),
            chunk_summaries=chunk_summaries,
            warning=f"{first_pass.warning} 当前兼容输出风格：{template_name}。",
        )

    def _extract_candidate_points(self, transcript_result: TranscriptBundle | TranscriptResult) -> list[str]:
        points: list[str] = []
        for chunk in transcript_result.chunks:
            sentences = self._split_sentences(chunk.text)
            for sentence in sentences:
                if len(sentence) < 12:
                    continue
                if any(keyword in sentence for keyword in FILLER_KEYWORDS):
                    continue
                points.append(sentence)
        return dedupe_keep_order(points)

    def _infer_value_rating(self, high_value_points: list[str], cleaned_transcript: str) -> str:
        if len(high_value_points) >= 6 and len(cleaned_transcript) > 400:
            return "高价值"
        if len(high_value_points) >= 3:
            return "值得看"
        if cleaned_transcript and len(cleaned_transcript) > 200:
            return "普通"
        return "不值得"

    def _build_value_reason(self, value_rating: str, high_value_points: list[str], cleaned_transcript: str) -> str:
        if value_rating == "高价值":
            return "整理后仍能提炼出多条独立信息点，说明内容不只是情绪表达或铺垫。"
        if value_rating == "值得看":
            return "可以提炼出少量有用观点，但整体信息密度还不算特别高。"
        if value_rating == "普通":
            return "转录文本较长，但稳定可提炼的信息点较少，重复表达偏多。"
        if not cleaned_transcript.strip():
            return "原始文本过少，暂时无法判断稳定价值。"
        return "文本里更多是铺垫、泛泛表达或低信息密度内容。"

    def _build_headline_verdict(self, value_rating: str, high_value_points: list[str]) -> str:
        if high_value_points:
            return f"这份内容{value_rating}，核心可保留信息集中在：{high_value_points[0]}"
        return f"这份内容{value_rating}，暂时没有提炼出明确干货。"

    def _build_one_line_verdict(self, value_rating: str, high_value_points: list[str]) -> str:
        if high_value_points:
            return f"{value_rating}，核心价值在于 {high_value_points[0]}"
        return f"{value_rating}，当前没有提炼出稳定可复用的信息。"

    def _build_generated_title(
        self,
        transcript_result: TranscriptBundle | TranscriptResult,
        high_value_points: list[str],
        value_rating: str,
    ) -> str | None:
        source_name = ""
        if isinstance(transcript_result, TranscriptBundle):
            source_name = normalize_whitespace(transcript_result.source.display_name)
        source_name = re.sub(r"\s+", "", source_name)
        source_name = re.sub(r"\.(mp3|mp4|wav|m4a|txt|docx?)$", "", source_name, flags=re.IGNORECASE)
        source_name = source_name[:10]

        point = normalize_whitespace(high_value_points[0]) if high_value_points else ""
        point = re.sub(r"[，。！？；：,.!?;:]+", " ", point).strip()[:12]

        if source_name and point:
            return f"{source_name}：{point}"
        if source_name:
            return f"{source_name}内容整理"
        if point:
            return f"{point}整理初稿"
        return f"{value_rating}内容整理"

    def _build_objective_context(self, high_value_points: list[str]) -> list[str]:
        context: list[str] = []
        for item in high_value_points[:4]:
            if any(token in item for token in ("模型", "算法", "系统", "策略", "结构", "方法")):
                context.append(f"该段内容涉及概念或方法描述，阅读时应重点关注它的定义边界：{item}")
            else:
                context.append(f"这条信息更适合作为后续理解或检索关键词：{item}")
        return context

    def _build_low_value_segments(self, transcript_result: TranscriptBundle | TranscriptResult) -> list[LowValueSegment]:
        results: list[LowValueSegment] = []
        for chunk in transcript_result.chunks:
            text = normalize_whitespace(chunk.text)
            if not text:
                continue
            reason = None
            if any(keyword in text for keyword in FILLER_KEYWORDS):
                reason = "包含明显铺垫、互动或平台话术"
            elif len(text) < 20:
                reason = "信息量较低"
            elif len(set(text)) < max(6, len(text) // 5):
                reason = "重复表达偏多"
            if reason:
                results.append(
                    LowValueSegment(
                        start=chunk.start,
                        end=chunk.end,
                        reason=reason,
                        excerpt=text[:120],
                    )
                )
        return results[:6]

    def _build_draft_paragraphs(
        self,
        paragraphs: list[str],
        low_value_segments: list[LowValueSegment],
    ) -> list[DraftParagraphLabel]:
        results: list[DraftParagraphLabel] = []
        low_excerpts = [item.excerpt for item in low_value_segments if item.excerpt]
        total = len(paragraphs)
        for index, paragraph in enumerate(paragraphs, start=1):
            if any(excerpt and excerpt[:24] in paragraph for excerpt in low_excerpts):
                results.append(
                    DraftParagraphLabel(
                        index=index,
                        text=paragraph,
                        value_level="low",
                        reason="该段疑似铺垫、互动或重复表达偏多。",
                    )
                )
                continue

            compact = normalize_whitespace(paragraph)
            if len(compact) >= 180 and index == 1:
                level = "high"
            elif len(compact) >= 140 and index <= max(2, total // 3):
                level = "worth"
            elif len(compact) < 48:
                level = "low"
            else:
                level = "normal"

            results.append(
                DraftParagraphLabel(
                    index=index,
                    text=paragraph,
                    value_level=level,
                    reason="",
                )
            )
        return results

    def _build_template_overview(self, first_pass: FirstPassResult, template_id: str) -> str:
        if template_id == "minimal-summary":
            return first_pass.headline_verdict
        if template_id == "action-extraction":
            return "把内容拆成可直接执行的原文动作，以及基于内容延伸出的建议动作。"
        if template_id == "course-notes":
            return "把内容重组为便于复习的课程笔记结构，尽量保留可回看重点。"
        if template_id == "expert-review":
            return "从专业视角判断这份内容的可信度、价值密度和可能遗漏的前提。"
        return "围绕学习理解对内容进行更系统的展开和重组。"

    def _build_template_key_points(self, first_pass: FirstPassResult, template_id: str) -> list[str]:
        if template_id == "minimal-summary":
            return first_pass.high_value_points[:3]
        if template_id == "expert-review":
            points = [
                f"价值判断：{first_pass.value_rating}",
                f"主要依据：{first_pass.value_reason}",
            ]
            if first_pass.high_value_points:
                points.append(f"最值得保留的观点：{first_pass.high_value_points[0]}")
            return points
        return first_pass.high_value_points[:6]

    def _build_template_sections(self, first_pass: FirstPassResult, template_id: str) -> list[TemplateSection]:
        if template_id == "minimal-summary":
            return [
                TemplateSection(
                    title="核心结论",
                    summary=first_pass.headline_verdict,
                    bullets=first_pass.high_value_points[:3],
                )
            ]
        if template_id == "action-extraction":
            source_actions = self._extract_action_items(first_pass.cleaned_transcript)[:5]
            ai_actions = [
                f"如果要把第 {index + 1} 条信息真正落地，可以先做一个最小验证动作。"
                for index, _ in enumerate(first_pass.high_value_points[:3])
            ]
            return [
                TemplateSection(
                    title="原文动作",
                    summary="只保留原文里可以直接执行或明确指向下一步的动作。",
                    bullets=source_actions or ["原文中没有特别明确的动作项。"],
                ),
                TemplateSection(
                    title="AI延伸建议",
                    summary="基于原文内容延伸出的下一步建议，和原文动作区分展示。",
                    bullets=ai_actions,
                ),
            ]
        if template_id == "course-notes":
            return [
                TemplateSection(
                    title="课程主线",
                    summary="先记住内容主线，再回看细节。",
                    bullets=first_pass.high_value_points[:4],
                ),
                TemplateSection(
                    title="理解补充",
                    summary="这些补充更适合当成复习时的提示卡片。",
                    bullets=first_pass.objective_context[:4],
                ),
            ]
        if template_id == "expert-review":
            strengths = first_pass.high_value_points[:3]
            limitations = [item.reason for item in first_pass.low_value_segments[:3]] or ["没有检测到明显低价值片段。"]
            return [
                TemplateSection(
                    title="内容优点",
                    summary="这些部分说明内容确实有可保留的信息。",
                    bullets=strengths,
                ),
                TemplateSection(
                    title="内容局限",
                    summary="这些部分提醒你不要把整份内容视为同等可信或同等重要。",
                    bullets=limitations,
                ),
            ]
        return [
            TemplateSection(
                title="核心知识",
                summary="按学习顺序重看最有价值的部分。",
                bullets=first_pass.high_value_points[:4],
            ),
            TemplateSection(
                title="理解辅助",
                summary="这些内容适合帮助你把原文吃透，而不是只记结论。",
                bullets=first_pass.objective_context[:4],
            ),
        ]

    def _build_template_fields(self, first_pass: FirstPassResult, template_id: str) -> dict[str, object]:
        if template_id == "study-deep-dive":
            return {
                "学习问题": [
                    f"这条观点为什么成立：{point}"
                    for point in first_pass.high_value_points[:3]
                ],
                "复习提醒": first_pass.objective_context[:3],
            }
        if template_id == "minimal-summary":
            return {"一句话": first_pass.headline_verdict}
        if template_id == "action-extraction":
            return {
                "原文动作": self._extract_action_items(first_pass.cleaned_transcript)[:5],
                "AI延伸建议": [
                    "先选一条动作做最小验证，再决定是否继续投入。",
                    "如果原文没有明确动作，就把观点转成可观察的实验。",
                ],
            }
        if template_id == "course-notes":
            return {
                "术语提示": first_pass.objective_context[:4],
                "复习清单": first_pass.high_value_points[:5],
            }
        if template_id == "expert-review":
            return {
                "原文依据": first_pass.high_value_points[:4],
                "专业判断": [
                    f"整体评价：{first_pass.value_rating}",
                    "如果要真正采用其中观点，建议回到原始资料做二次核对。",
                ],
            }
        return {}

    def _summarize_chunk(self, chunk: TranscriptChunk) -> ChunkSummary:
        sentences = self._split_sentences(chunk.text)
        if sentences:
            title = sentences[0][:18]
        elif has_timeline(chunk.start, chunk.end):
            title = f"{format_timestamp(chunk.start)} 内容摘要"
        else:
            title = f"第 {chunk.index} 组段落摘要"
        summary = "；".join(sentences[:2]) if sentences else "该片段暂无可提炼摘要。"
        key_points = [sentence for sentence in sentences[:3] if len(sentence) >= 6]
        action_items = self._extract_action_items(chunk.text)
        return ChunkSummary(
            index=chunk.index,
            start=chunk.start,
            end=chunk.end,
            title=title,
            summary=summary,
            key_points=key_points,
            action_items=action_items,
        )

    def _extract_action_items(self, text: str) -> list[str]:
        keywords = ("需要", "下一步", "安排", "跟进", "执行", "验证", "记录", "整理")
        result = [sentence for sentence in self._split_sentences(text) if any(keyword in sentence for keyword in keywords)]
        return dedupe_keep_order(result)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        sentences = re.split(r"[。！？\n]", text)
        return [normalize_whitespace(sentence.strip(" ,，；;")) for sentence in sentences if normalize_whitespace(sentence)]
