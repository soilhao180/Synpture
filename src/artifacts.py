from __future__ import annotations

import json
from pathlib import Path

from src.models import (
    AcquisitionResult,
    DraftParagraphLabel,
    FirstPassResult,
    InputSource,
    LowValueSegment,
    TemplateResult,
    TemplateSection,
    TranscriptBundle,
    TranscriptSegment,
)
from src.utils import write_json, write_text


def persist_source_artifacts(run_dir: Path, transcript_bundle: TranscriptBundle) -> tuple[Path, Path]:
    input_source_path = write_json(run_dir / "input_source.json", serialize_input_source(transcript_bundle.source))
    acquisition_path = write_json(
        run_dir / "acquisition_result.json",
        serialize_acquisition_result(transcript_bundle.acquisition),
    )
    return input_source_path, acquisition_path


def persist_transcript_artifacts(run_dir: Path, transcript_bundle: TranscriptBundle) -> tuple[Path, Path, Path]:
    transcript_path = write_text(run_dir / "transcript.txt", transcript_bundle.transcript_text)
    segments_path = write_json(
        run_dir / "segments.json",
        {
            "segments": [serialize_segment(segment) for segment in transcript_bundle.segments],
        },
    )
    chunks_path = write_json(
        run_dir / "chunks.json",
        {
            "chunks": [
                {
                    "index": chunk.index,
                    "start": chunk.start,
                    "end": chunk.end,
                    "text": chunk.text,
                }
                for chunk in transcript_bundle.chunks
            ]
        },
    )
    return transcript_path, segments_path, chunks_path


def serialize_input_source(source: InputSource) -> dict:
    return {
        "source_id": source.source_id,
        "entry_type": source.entry_type,
        "content_type": source.content_type,
        "display_name": source.display_name,
        "original_filename": source.original_filename,
        "mime_type": source.mime_type,
        "local_path": str(source.local_path) if source.local_path else None,
        "text_content": source.text_content,
        "url": source.url,
        "metadata": source.metadata,
    }


def serialize_segment(segment: TranscriptSegment) -> dict:
    return {
        "index": segment.index,
        "start": segment.start,
        "end": segment.end,
        "text": segment.text,
    }


def serialize_acquisition_result(acquisition_result: AcquisitionResult) -> dict:
    return {
        "source_id": acquisition_result.source.source_id,
        "acquisition_mode": acquisition_result.acquisition_mode,
        "display_text": acquisition_result.display_text,
        "segments": [serialize_segment(segment) for segment in acquisition_result.segments],
        "artifacts": {key: str(value) for key, value in acquisition_result.artifacts.items()},
        "notes": acquisition_result.notes,
        "failure_reason": acquisition_result.failure_reason,
    }


def load_input_source(path: Path) -> InputSource:
    payload = json.loads(path.read_text(encoding="utf-8"))
    local_path_value = payload.get("local_path")
    return InputSource(
        source_id=str(payload.get("source_id", "")),
        entry_type=str(payload.get("entry_type", "local_media")),  # type: ignore[arg-type]
        content_type=str(payload.get("content_type", "plain_text")),  # type: ignore[arg-type]
        display_name=str(payload.get("display_name", "")),
        original_filename=str(payload.get("original_filename")) if payload.get("original_filename") is not None else None,
        mime_type=str(payload.get("mime_type")) if payload.get("mime_type") is not None else None,
        local_path=Path(str(local_path_value)) if local_path_value else None,
        text_content=str(payload.get("text_content")) if payload.get("text_content") is not None else None,
        url=str(payload.get("url")) if payload.get("url") is not None else None,
        metadata=dict(payload.get("metadata", {})),
    )


def load_acquisition_result(path: Path, source: InputSource) -> AcquisitionResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AcquisitionResult(
        source=source,
        acquisition_mode=str(payload.get("acquisition_mode", "direct_text")),  # type: ignore[arg-type]
        display_text=str(payload.get("display_text", "")),
        segments=[
            TranscriptSegment(
                index=int(item.get("index", index)),
                start=float(item["start"]) if item.get("start") is not None else None,
                end=float(item["end"]) if item.get("end") is not None else None,
                text=str(item.get("text", "")),
            )
            for index, item in enumerate(payload.get("segments", []), start=1)
        ],
        artifacts={
            str(key): Path(str(value))
            for key, value in dict(payload.get("artifacts", {})).items()
            if value is not None
        },
        notes=[str(item) for item in payload.get("notes", [])],
        failure_reason=str(payload.get("failure_reason")) if payload.get("failure_reason") is not None else None,
    )


def serialize_first_pass(first_pass: FirstPassResult) -> dict:
    return {
        "provider": first_pass.provider,
        "model": first_pass.model,
        "cleaned_transcript": first_pass.cleaned_transcript,
        "one_line_verdict": first_pass.one_line_verdict,
        "headline_verdict": first_pass.headline_verdict,
        "value_rating": first_pass.value_rating,
        "value_reason": first_pass.value_reason,
        "high_value_points": first_pass.high_value_points,
        "objective_context": first_pass.objective_context,
        "low_value_segments": [
            {
                "start": item.start,
                "end": item.end,
                "reason": item.reason,
                "excerpt": item.excerpt,
            }
            for item in first_pass.low_value_segments
        ],
        "raw_transcript_reference": first_pass.raw_transcript_reference,
        "draft_paragraphs": [
            {
                "index": item.index,
                "text": item.text,
                "value_level": item.value_level,
                "reason": item.reason,
            }
            for item in first_pass.draft_paragraphs
        ],
        "uncertainty_notes": first_pass.uncertainty_notes,
        "needs_human_check_timestamps": first_pass.needs_human_check_timestamps,
        "generated_title": first_pass.generated_title,
        "warning": first_pass.warning,
    }


def serialize_template_result(template_result: TemplateResult) -> dict:
    return {
        "template_id": template_result.template_id,
        "template_name": template_result.template_name,
        "provider": template_result.provider,
        "model": template_result.model,
        "overview": template_result.overview,
        "key_points": template_result.key_points,
        "section_summaries": [
            {
                "title": item.title,
                "summary": item.summary,
                "bullets": item.bullets,
            }
            for item in template_result.section_summaries
        ],
        "template_fields": template_result.template_fields,
        "warning": template_result.warning,
    }


def load_first_pass(path: Path) -> FirstPassResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return FirstPassResult(
        provider=str(payload.get("provider", "unknown")),
        model=str(payload.get("model", "unknown")),
        cleaned_transcript=str(payload.get("cleaned_transcript", "")),
        one_line_verdict=str(payload.get("one_line_verdict", "")),
        headline_verdict=str(payload.get("headline_verdict", "")),
        value_rating=str(payload.get("value_rating", "")),
        value_reason=str(payload.get("value_reason", "")),
        high_value_points=[str(item) for item in payload.get("high_value_points", [])],
        objective_context=[str(item) for item in payload.get("objective_context", [])],
        low_value_segments=[
            LowValueSegment(
                start=float(item["start"]) if item.get("start") is not None else None,
                end=float(item["end"]) if item.get("end") is not None else None,
                reason=str(item.get("reason", "")),
                excerpt=str(item.get("excerpt", "")),
            )
            for item in payload.get("low_value_segments", [])
        ],
        raw_transcript_reference=str(payload.get("raw_transcript_reference", "")),
        draft_paragraphs=[
            DraftParagraphLabel(
                index=int(item.get("index", idx)),
                text=str(item.get("text", "")),
                value_level=str(item.get("value_level", "")),
                reason=str(item.get("reason", "")),
            )
            for idx, item in enumerate(payload.get("draft_paragraphs", []), start=1)
        ],
        uncertainty_notes=[str(item) for item in payload.get("uncertainty_notes", [])],
        needs_human_check_timestamps=[str(item) for item in payload.get("needs_human_check_timestamps", [])],
        generated_title=str(payload.get("generated_title")).strip() if payload.get("generated_title") is not None else None,
        warning=str(payload.get("warning")) if payload.get("warning") is not None else None,
    )


def load_template_result(path: Path) -> TemplateResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TemplateResult(
        template_id=str(payload.get("template_id", "")),
        template_name=str(payload.get("template_name", "")),
        provider=str(payload.get("provider", "unknown")),
        model=str(payload.get("model", "unknown")),
        overview=str(payload.get("overview", "")),
        key_points=[str(item) for item in payload.get("key_points", [])],
        section_summaries=[
            TemplateSection(
                title=str(item.get("title", "")),
                summary=str(item.get("summary", "")),
                bullets=[str(bullet) for bullet in item.get("bullets", [])],
            )
            for item in payload.get("section_summaries", [])
        ],
        template_fields=dict(payload.get("template_fields", {})),
        warning=str(payload.get("warning")) if payload.get("warning") is not None else None,
    )


def persist_gpu_diagnostics(
    run_dir: Path,
    diagnostics: list[dict],
) -> tuple[Path, Path]:
    json_path = write_json(run_dir / "gpu_diagnostics.json", {"entries": diagnostics})

    lines = [
        "# GPU Diagnostics",
        "",
    ]
    for entry in diagnostics:
        lines.extend(
            [
                f"## {entry.get('event', 'event')}",
                f"- time: {entry.get('timestamp', '')}",
                f"- chunk: {entry.get('chunk_index', '-')}/{entry.get('chunk_total', '-')}",
                f"- device: {entry.get('device', '-')}",
                f"- pid: {entry.get('worker_pid', '-')}",
                f"- return_code: {entry.get('return_code', '-')}",
                f"- gpu_memory_used_mb: {entry.get('gpu_memory_used_mb', '-')}",
                f"- gpu_utilization_percent: {entry.get('gpu_utilization_percent', '-')}",
                f"- result_exists: {entry.get('result_exists', '-')}",
                f"- segment_count: {entry.get('segment_count', '-')}",
                f"- note: {entry.get('note', '')}",
                "",
            ]
        )
    md_path = write_text(run_dir / "gpu_diagnostics.md", "\n".join(lines).strip() + "\n")
    return json_path, md_path
