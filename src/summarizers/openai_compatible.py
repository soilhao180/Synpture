from __future__ import annotations

import json
from typing import Any

from src.models import (
    ChunkSummary,
    DraftParagraphLabel,
    FirstPassResult,
    LowValueSegment,
    StructuredSummary,
    TemplateDefinition,
    TemplateResult,
    TemplateSection,
    TestResult,
    TranscriptBundle,
    TranscriptResult,
)
from src.utils import dedupe_keep_order, extract_json_object, format_timestamp, has_timeline


class OpenAICompatibleSummarizer:
    provider = "openai-compatible"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url

        if client is not None:
            self.client = client
            return

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("未安装 `openai` 依赖，无法使用远程总结能力。") from exc

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = OpenAI(**client_kwargs)

    def ping(self) -> TestResult:
        request_summary = "GET /models"
        try:
            response = self.client.models.list()
            payload = self._to_dict(response)
            data = payload.get("data", []) if isinstance(payload, dict) else []
            preview = ", ".join(str(item.get("id", "")) for item in data[:5] if item.get("id"))
            return TestResult(
                ok=True,
                kind="summary_connection",
                message="连接成功，基础模型列表可访问。",
                raw_preview=preview or "已返回 /models 列表。",
                request_summary=request_summary,
                status_code=200,
            )
        except Exception as exc:
            return self._build_error_result(
                kind="summary_connection",
                message="连接失败，未通过基础 OpenAI-compatible 测试。",
                request_summary=request_summary,
                exc=exc,
            )

    def list_models(self) -> TestResult:
        request_summary = "GET /models"
        try:
            response = self.client.models.list()
            payload = self._to_dict(response)
            data = payload.get("data", []) if isinstance(payload, dict) else []
            models = [str(item.get("id", "")).strip() for item in data if str(item.get("id", "")).strip()]
            preview = ", ".join(models[:10])
            return TestResult(
                ok=bool(models),
                kind="summary_list_models",
                message=f"已获取到 {len(models)} 个可用模型。" if models else "未获取到可用模型列表。",
                raw_preview=preview or None,
                request_summary=request_summary,
                status_code=200,
                models=models,
            )
        except Exception as exc:
            return self._build_error_result(
                kind="summary_list_models",
                message="获取可用模型失败。",
                request_summary=request_summary,
                exc=exc,
            )

    def test_model_call(self, model_name: str | None = None) -> TestResult:
        active_model = model_name or self.model
        request_summary = f"chat.completions.create(stream=True, model={active_model})"
        try:
            content = self._stream_chat_text(
                model=active_model,
                system_prompt="你是一个简洁的中文助手。",
                user_prompt="你好，请回复一句简体中文，证明你可以正常响应。",
                temperature=0,
            ).strip()
            if not content:
                raise ValueError("模型没有返回可读文本。")
            return TestResult(
                ok=True,
                kind="summary_model_call",
                message="模型调用成功，已返回可读文本。",
                raw_preview=content[:500],
                request_summary=request_summary,
                status_code=200,
                model_name=active_model,
            )
        except Exception as exc:
            return self._build_error_result(
                kind="summary_model_call",
                message="模型调用失败，请检查模型名、鉴权或接口兼容性。",
                request_summary=request_summary,
                exc=exc,
                model_name=active_model,
            )

    def run_first_pass(self, transcript_result: TranscriptBundle | TranscriptResult) -> FirstPassResult:
        chunk_digest = [
            {
                "index": chunk.index,
                "label": self._chunk_label(chunk.index, chunk.start, chunk.end),
                "text": chunk.text,
            }
            for chunk in transcript_result.chunks
        ]
        timeline_instruction = (
            "如果输入带有真实时间轴，low_value_segments 里的 start 和 end 必须填写秒数。"
            if any(has_timeline(chunk.start, chunk.end) for chunk in transcript_result.chunks)
            else "如果输入没有真实时间轴，low_value_segments 里的 start 和 end 必须返回 null，禁止伪造秒数。"
        )
        prompt = f"""
你是一个中文长内容整理助手。请根据以下转录内容，输出第一稿标准结果。

硬性要求：
1. 只返回一个 JSON 对象，不要输出解释，不要输出 Markdown 代码块。
2. 全部使用简体中文。
3. 你的任务是把原始转录整理成可读初稿，但不能胡乱扩写。只允许做最小必要修正：纠错、断句、去口水、补全明显缺失的连接词。
4. 如果原始内容里出现英文词、品牌名、术语、缩写或你不确定的外来词，不要把“联网核实”交给外部预处理；你自己判断是否需要联网核实，再决定如何写入结果。
5. generated_title 必须是内容标题，不是评价句。优先包含作者、说话人或来源主体；如果能从材料判断出“谁在说”，就把这个主体自然写进标题。标题长度控制在 10 到 24 个中文字符，不要标题党。
6. one_line_verdict 是唯一那句“值不值得看”的一句话判断，要短、稳、明确，例如“值得看，核心价值在于……”。不要再把这句话塞进标题。
7. headline_verdict 可以是一句更完整的总结句，但它不是标题，不要写成标题口吻。
8. value_rating 只能从这四档里选一个：高价值、值得看、普通、不值得。
9. 评级的第一依据是客观的信息密度，而不是用户偏好。重点看：真正有意义内容占比、口水话和套话占比、情绪发泄是否过多、是否存在可复用的判断、步骤、经验或结论。
10. value_reason 说明为什么给出这个评级，但这个字段是给系统使用的，不要把它写进初稿正文。
11. high_value_points 输出 4 到 8 条最值得保留的高价值信息。
12. objective_context 输出 2 到 6 条客观背景上下文，只能补充背景、术语定义、前提条件或理解线索，不能做主观评价。
13. uncertainty_notes 输出存在歧义、疑似转录错误、概念不确定或需要人工留意的说明；没有就返回空数组。
14. needs_human_check_timestamps 输出需要人工回看原稿时间戳的位置说明；没有就返回空数组。
15. low_value_segments 输出数组，每项包含 start、end、reason、excerpt。{timeline_instruction}
16. draft_paragraphs 输出段落级数组，用于前端按正文段落直接区分高价值、普通、低价值内容。每段必须包含 index、text、value_level、reason。
17. draft_paragraphs 里的 value_level 只能是 high、normal、low。
18. 初稿正文必须是可直接阅读的正文段落，不要写成提纲，不要在正文里显式解释“为什么高价值”。
19. cleaned_transcript 要和 draft_paragraphs 的 text 内容一致，只是 cleaned_transcript 是完整拼接版。
20. raw_transcript_reference 原样返回原始转录文本。

原始转录文本：
{transcript_result.transcript_text}

分段输入：
{json.dumps(chunk_digest, ensure_ascii=False, indent=2)}

JSON 格式：
{{
  "generated_title": "...",
  "one_line_verdict": "...",
  "cleaned_transcript": "...",
  "headline_verdict": "...",
  "value_rating": "高价值",
  "value_reason": "...",
  "high_value_points": ["..."],
  "objective_context": ["..."],
  "draft_paragraphs": [
    {{
      "index": 1,
      "text": "...",
      "value_level": "high",
      "reason": "..."
    }}
  ],
  "low_value_segments": [
    {{
      "start": null,
      "end": null,
      "reason": "...",
      "excerpt": "..."
    }}
  ],
  "uncertainty_notes": ["..."],
  "needs_human_check_timestamps": ["..."],
  "raw_transcript_reference": "..."
}}
""".strip()
        payload = self._complete_json(prompt)
        return FirstPassResult(
            provider=self.provider,
            model=self.model,
            cleaned_transcript=str(payload.get("cleaned_transcript", "")).strip(),
            one_line_verdict=str(payload.get("one_line_verdict", "")).strip(),
            headline_verdict=str(payload.get("headline_verdict", "")).strip(),
            value_rating=str(payload.get("value_rating", "")).strip(),
            value_reason=str(payload.get("value_reason", "")).strip(),
            high_value_points=[str(item).strip() for item in payload.get("high_value_points", []) if str(item).strip()],
            objective_context=[str(item).strip() for item in payload.get("objective_context", []) if str(item).strip()],
            low_value_segments=[
                LowValueSegment(
                    start=float(item["start"]) if item.get("start") is not None else None,
                    end=float(item["end"]) if item.get("end") is not None else None,
                    reason=str(item.get("reason", "")).strip(),
                    excerpt=str(item.get("excerpt", "")).strip(),
                )
                for item in payload.get("low_value_segments", [])
            ],
            raw_transcript_reference=str(payload.get("raw_transcript_reference", transcript_result.transcript_text)),
            draft_paragraphs=[
                DraftParagraphLabel(
                    index=int(item.get("index", idx)),
                    text=str(item.get("text", "")).strip(),
                    value_level=str(item.get("value_level", "normal")).strip(),
                    reason=str(item.get("reason", "")).strip(),
                )
                for idx, item in enumerate(payload.get("draft_paragraphs", []), start=1)
                if str(item.get("text", "")).strip()
            ],
            uncertainty_notes=[str(item).strip() for item in payload.get("uncertainty_notes", []) if str(item).strip()],
            needs_human_check_timestamps=[
                str(item).strip() for item in payload.get("needs_human_check_timestamps", []) if str(item).strip()
            ],
            generated_title=str(payload.get("generated_title", "")).strip() or None,
        )

    def run_template_pass(
        self,
        first_pass: FirstPassResult,
        template_definition: TemplateDefinition,
    ) -> TemplateResult:
        prompt = f"""
你是一个中文内容产品的模板化二次处理器。请基于以下首轮底稿，输出模板结果。

模板信息：
- template_id: {template_definition.id}
- template_name: {template_definition.name}
- description: {template_definition.description}
- prompt_instructions: {template_definition.prompt_instructions}

首轮底稿：
{{
  "cleaned_transcript": {json.dumps(first_pass.cleaned_transcript, ensure_ascii=False)},
  "headline_verdict": {json.dumps(first_pass.headline_verdict, ensure_ascii=False)},
  "value_rating": {json.dumps(first_pass.value_rating, ensure_ascii=False)},
  "value_reason": {json.dumps(first_pass.value_reason, ensure_ascii=False)},
  "high_value_points": {json.dumps(first_pass.high_value_points, ensure_ascii=False)},
  "objective_context": {json.dumps(first_pass.objective_context, ensure_ascii=False)},
  "low_value_segments": {json.dumps([
      {{
          "start": item.start,
          "end": item.end,
          "reason": item.reason,
          "excerpt": item.excerpt,
      }}
      for item in first_pass.low_value_segments
  ], ensure_ascii=False)}
}}

输出要求：
1. 只返回一个 JSON 对象，不要解释。
2. overview 是该模板结果的总览。
3. key_points 输出该模板下最关键的要点。
4. section_summaries 是数组，每项包含 title、summary、bullets。
5. template_fields 是模板专属的附加字段。
6. 如果模板是 action-extraction，必须显式区分“原文动作”和“AI 延伸建议”。
7. 如果模板是 expert-review，必须同时给出“原文依据”和“专业判断”。

JSON 格式：
{{
  "overview": "...",
  "key_points": ["..."],
  "section_summaries": [
    {{
      "title": "...",
      "summary": "...",
      "bullets": ["..."]
    }}
  ],
  "template_fields": {{
    "字段A": ["..."]
  }}
}}
""".strip()
        payload = self._complete_json(prompt)
        return TemplateResult(
            template_id=template_definition.id,
            template_name=template_definition.name,
            provider=self.provider,
            model=self.model,
            overview=str(payload.get("overview", "")).strip(),
            key_points=[str(item).strip() for item in payload.get("key_points", []) if str(item).strip()],
            section_summaries=[
                TemplateSection(
                    title=str(item.get("title", "")).strip(),
                    summary=str(item.get("summary", "")).strip(),
                    bullets=[str(bullet).strip() for bullet in item.get("bullets", []) if str(bullet).strip()],
                )
                for item in payload.get("section_summaries", [])
            ],
            template_fields=dict(payload.get("template_fields", {})),
            template_source=template_definition.source,
            template_version=template_definition.version,
        )

    def summarize(self, transcript_result: TranscriptBundle | TranscriptResult, style: str) -> StructuredSummary:
        chunk_summaries = [self._summarize_chunk(chunk, style) for chunk in transcript_result.chunks]
        overall = self._summarize_overall(chunk_summaries, style)
        merged_key_points = dedupe_keep_order(
            [str(item).strip() for item in overall.get("key_points", []) if str(item).strip()]
            + [point for chunk in chunk_summaries for point in chunk.key_points]
        )
        merged_actions = dedupe_keep_order(
            [str(item).strip() for item in overall.get("action_items", []) if str(item).strip()]
            + [action for chunk in chunk_summaries for action in chunk.action_items]
        )
        return StructuredSummary(
            provider=self.provider,
            model=self.model,
            overall_summary=str(overall.get("overall_summary", "未生成整体摘要。")).strip(),
            key_points=merged_key_points[:12],
            action_items=merged_actions,
            chunk_summaries=chunk_summaries,
        )

    def _summarize_chunk(self, chunk, style: str) -> ChunkSummary:
        prompt = f"""
你是一个中文内容整理助手。请基于以下片段转录输出结构化 JSON。

要求：
1. 只返回一个 JSON 对象。
2. title 保持简短。
3. summary 用 1 到 2 句话概括。
4. key_points 是信息点数组。
5. action_items 只保留明确动作。
6. 当前输出风格提示：{style}

片段标签：{self._chunk_label(chunk.index, chunk.start, chunk.end)}
转录内容：{chunk.text}

JSON 格式：
{{
  "title": "章节标题",
  "summary": "这一段的摘要",
  "key_points": ["要点1"],
  "action_items": ["动作1"]
}}
""".strip()
        payload = self._complete_json(prompt)
        default_title = (
            f"{format_timestamp(chunk.start)} 内容摘要"
            if has_timeline(chunk.start, chunk.end)
            else f"第 {chunk.index} 组段落摘要"
        )
        return ChunkSummary(
            index=chunk.index,
            start=chunk.start,
            end=chunk.end,
            title=str(payload.get("title", default_title)).strip(),
            summary=str(payload.get("summary", "未生成摘要。")).strip(),
            key_points=[str(item).strip() for item in payload.get("key_points", []) if str(item).strip()],
            action_items=[str(item).strip() for item in payload.get("action_items", []) if str(item).strip()],
        )

    def _complete_json(self, prompt: str) -> dict[str, Any]:
        content = self._stream_chat_text(
            model=self.model,
            system_prompt="你是一个严谨的中文内容整理助手。请只返回一个 JSON 对象。",
            user_prompt=prompt,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        if not content.strip():
            raise ValueError("模型没有返回结构化内容。")
        return extract_json_object(content)

    def _summarize_overall(self, chunk_summaries: list[ChunkSummary], style: str) -> dict[str, Any]:
        chunk_digest = [
            {
                "label": self._chunk_label(chunk.index, chunk.start, chunk.end),
                "title": chunk.title,
                "summary": chunk.summary,
                "key_points": chunk.key_points,
                "action_items": chunk.action_items,
            }
            for chunk in chunk_summaries
        ]
        prompt = f"""
你是一个中文内容整理助手。请根据分段摘要输出整体结构化结果。

要求：
1. 只返回一个 JSON 对象。
2. overall_summary 用一段话给出整体总结。
3. key_points 输出最重要的 5 到 8 条要点。
4. action_items 只保留明确动作，没有则返回 []。
5. 当前输出风格提示：{style}

分段摘要：
{json.dumps(chunk_digest, ensure_ascii=False, indent=2)}

JSON 格式：
{{
  "overall_summary": "整体总结",
  "key_points": ["要点1"],
  "action_items": ["动作1"]
}}
""".strip()
        return self._complete_json(prompt)

    def _chunk_label(self, index: int, start: float | None, end: float | None) -> str:
        if has_timeline(start, end):
            return f"{format_timestamp(start)} - {format_timestamp(end)}"
        return f"第 {index} 组段落"

    def _stream_chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "stream": True,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        stream = self.client.chat.completions.create(**kwargs)
        fragments: list[str] = []
        for event in stream:
            fragments.extend(self._extract_stream_chunk_text(event))
        return "".join(fragment for fragment in fragments if fragment)

    def _extract_stream_chunk_text(self, event: Any) -> list[str]:
        texts: list[str] = []
        choices = getattr(event, "choices", None)
        if choices is None and isinstance(event, dict):
            choices = event.get("choices")

        if choices:
            for choice in choices:
                delta = getattr(choice, "delta", None)
                if delta is None and isinstance(choice, dict):
                    delta = choice.get("delta")
                texts.extend(self._coerce_content_fragments(delta))
                if not texts:
                    message = getattr(choice, "message", None)
                    if message is None and isinstance(choice, dict):
                        message = choice.get("message")
                    texts.extend(self._coerce_content_fragments(message))
            return texts

        payload = self._to_dict(event)
        if payload:
            for choice in payload.get("choices", []):
                texts.extend(self._coerce_content_fragments(choice.get("delta")))
                if not texts:
                    texts.extend(self._coerce_content_fragments(choice.get("message")))
        return texts

    def _coerce_content_fragments(self, content: Any) -> list[str]:
        if content is None:
            return []
        if isinstance(content, str):
            return [content]
        if isinstance(content, list):
            fragments: list[str] = []
            for item in content:
                fragments.extend(self._coerce_content_fragments(item))
            return fragments
        if isinstance(content, dict):
            fragments: list[str] = []
            direct_content = content.get("content")
            if direct_content is not None:
                fragments.extend(self._coerce_content_fragments(direct_content))
            direct_text = content.get("text")
            if isinstance(direct_text, str):
                fragments.append(direct_text)
            return fragments

        nested_content = getattr(content, "content", None)
        if nested_content is not None:
            return self._coerce_content_fragments(nested_content)

        text = getattr(content, "text", None)
        if isinstance(text, str):
            return [text]
        return []

    @staticmethod
    def _to_dict(response: Any) -> dict[str, Any]:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if isinstance(response, dict):
            return response
        try:
            return json.loads(str(response))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_status_code(exc: Exception) -> int | None:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        response = getattr(exc, "response", None)
        if response is not None:
            code = getattr(response, "status_code", None)
            if isinstance(code, int):
                return code
        return None

    def _build_error_result(
        self,
        *,
        kind: str,
        message: str,
        request_summary: str,
        exc: Exception,
        model_name: str | None = None,
    ) -> TestResult:
        return TestResult(
            ok=False,
            kind=kind,
            message=f"{message} 原因：{exc}",
            raw_preview=None,
            request_summary=request_summary,
            status_code=self._extract_status_code(exc),
            model_name=model_name,
            models=[],
        )
