from __future__ import annotations

from src.models import FirstPassResult, TemplateDefinition, TemplateResult, TranscriptBundle, TranscriptResult
from src.utils import format_timestamp, has_timeline, timestamp_now


def render_first_pass_markdown(
    first_pass: FirstPassResult,
    transcript_result: TranscriptBundle | TranscriptResult,
) -> str:
    lines: list[str] = []
    title = _transcript_title(transcript_result)

    lines.append(f"# {title} - 首轮标准底稿")
    lines.append("")
    lines.append(f"- 处理时间：{timestamp_now()}")
    lines.extend(_build_source_summary_lines(transcript_result))
    lines.append(f"- 转录模型：{transcript_result.model_used}")
    lines.append(f"- 首轮模型：{first_pass.model}")
    lines.append("")

    if first_pass.warning:
        lines.append("## 提示")
        lines.append("")
        lines.append(first_pass.warning)
        lines.append("")

    lines.append("## 整理稿")
    lines.append("")
    lines.append(first_pass.cleaned_transcript or "暂无整理稿。")
    lines.append("")

    lines.append("## 结构化判断")
    lines.append("")
    lines.append(f"- 一句话结论：{first_pass.headline_verdict or '暂无'}")
    lines.append(f"- 价值判断：{first_pass.value_rating or '暂无'}")
    lines.append(f"- 判断原因：{first_pass.value_reason or '暂无'}")
    lines.append("")

    lines.append("### 干货提取")
    lines.append("")
    if first_pass.high_value_points:
        for item in first_pass.high_value_points:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无")
    lines.append("")

    lines.append("### 补充理解（客观）")
    lines.append("")
    if first_pass.objective_context:
        for item in first_pass.objective_context:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无")
    lines.append("")

    lines.append("### 低价值内容标注")
    lines.append("")
    if first_pass.low_value_segments:
        for item in first_pass.low_value_segments:
            lines.append(f"- {_format_low_value_label(item.start, item.end)} {item.reason}：{item.excerpt}")
    else:
        lines.append("- 暂无")
    lines.append("")

    lines.append("## 原始转录对照")
    lines.append("")
    lines.append(first_pass.raw_transcript_reference or transcript_result.transcript_text or "暂无原始转录。")
    lines.append("")

    return "\n".join(lines)


def render_template_markdown(
    template_result: TemplateResult,
    first_pass: FirstPassResult,
    transcript_result: TranscriptBundle | TranscriptResult,
    template_definition: TemplateDefinition,
) -> str:
    lines: list[str] = []
    title = _transcript_title(transcript_result)

    lines.append(f"# {title} - {template_result.template_name}")
    lines.append("")
    lines.append(f"- 处理时间：{timestamp_now()}")
    lines.extend(_build_source_summary_lines(transcript_result))
    lines.append(f"- 模板：{template_definition.name}")
    lines.append(f"- 模型：{template_result.model}")
    lines.append("")

    if template_result.warning:
        lines.append("## 提示")
        lines.append("")
        lines.append(template_result.warning)
        lines.append("")

    lines.append("## 总览")
    lines.append("")
    lines.append(template_result.overview or "暂无总览。")
    lines.append("")

    lines.append("## 要点")
    lines.append("")
    if template_result.key_points:
        for item in template_result.key_points:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无")
    lines.append("")

    lines.append("## 分段摘要")
    lines.append("")
    if template_result.section_summaries:
        for section in template_result.section_summaries:
            lines.append(f"### {section.title}")
            lines.append("")
            lines.append(section.summary or "暂无")
            lines.append("")
            for bullet in section.bullets:
                lines.append(f"- {bullet}")
            if section.bullets:
                lines.append("")
    else:
        lines.append("暂无分段摘要。")
        lines.append("")

    if template_result.template_fields:
        lines.append("## 模板附加字段")
        lines.append("")
        for key, value in template_result.template_fields.items():
            lines.append(f"### {key}")
            lines.append("")
            if isinstance(value, list):
                for item in value:
                    lines.append(f"- {item}")
            else:
                lines.append(str(value))
            lines.append("")

    lines.append("## 依据底稿")
    lines.append("")
    lines.append(first_pass.headline_verdict or "暂无")
    lines.append("")

    return "\n".join(lines)


def _transcript_title(transcript_result: TranscriptBundle | TranscriptResult) -> str:
    if isinstance(transcript_result, TranscriptBundle):
        return transcript_result.source.display_name
    return transcript_result.video_path.stem


def _build_source_summary_lines(transcript_result: TranscriptBundle | TranscriptResult) -> list[str]:
    if isinstance(transcript_result, TranscriptBundle):
        source = transcript_result.source
        acquisition = transcript_result.acquisition
        lines = [
            f"- 原始来源：{source.display_name}",
            f"- 入口类型：{source.entry_type}",
            f"- 取文方式：{acquisition.acquisition_mode}",
        ]
        if source.original_filename:
            lines.append(f"- 原始文件名：{source.original_filename}")
        if source.url:
            lines.append(f"- 原始链接：{source.url}")
        return lines
    return [f"- 原始文件：{transcript_result.video_path.name}"]


def _format_low_value_label(start: float | None, end: float | None) -> str:
    if has_timeline(start, end):
        return f"[{format_timestamp(start)} - {format_timestamp(end)}]"
    return "[无时间轴]"
