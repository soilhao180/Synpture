from __future__ import annotations

from src.models import PipelineStatus, TranscriptBundle, TranscriptResult
from src.utils import timestamp_now


PIPELINE_STAGE_META: dict[str, tuple[str, int]] = {
    "task_created": ("已创建任务", 5),
    "video_saved": ("已保存输入媒体", 10),
    "extracting_audio": ("正在提取音频", 25),
    "transcribing": ("正在执行转录", 45),
    "transcript_written": ("转录完成，正在写出中间产物", 60),
    "first_pass": ("正在生成首轮标准底稿", 78),
    "template_pass": ("正在生成二轮模板结果", 88),
    "rendering_markdown": ("正在写出结果文件", 94),
    "completed": ("处理完成", 100),
}


def build_status(stage_key: str, detail: str = "", **extra) -> PipelineStatus:
    stage_label, progress = PIPELINE_STAGE_META.get(stage_key, (stage_key, 0))
    return PipelineStatus(
        stage_key=stage_key,
        stage_label=stage_label,
        progress_percent=progress,
        detail=detail,
        updated_at=timestamp_now(),
        worker_pid=extra.get("worker_pid"),
        last_heartbeat_at=extra.get("last_heartbeat_at"),
        last_segment_at=extra.get("last_segment_at"),
        gpu_memory_used_mb=extra.get("gpu_memory_used_mb"),
        active_chunk_index=extra.get("active_chunk_index"),
        active_chunk_total=extra.get("active_chunk_total"),
    )


def build_failure_status(stage_key: str, detail: str, **extra) -> PipelineStatus:
    label, progress = PIPELINE_STAGE_META.get(stage_key, (stage_key, 0))
    return PipelineStatus(
        stage_key=f"{stage_key}_failed",
        stage_label=f"{label}失败",
        progress_percent=progress,
        detail=detail,
        updated_at=timestamp_now(),
        worker_pid=extra.get("worker_pid"),
        last_heartbeat_at=extra.get("last_heartbeat_at"),
        last_segment_at=extra.get("last_segment_at"),
        gpu_memory_used_mb=extra.get("gpu_memory_used_mb"),
        active_chunk_index=extra.get("active_chunk_index"),
        active_chunk_total=extra.get("active_chunk_total"),
    )


def build_summary_input_preview(transcript_result: TranscriptBundle | TranscriptResult, max_chars: int = 280) -> str:
    parts: list[str] = []
    for chunk in transcript_result.chunks[:2]:
        if chunk.text.strip():
            parts.append(chunk.text.strip())
    preview = "\n".join(parts).strip()
    if not preview:
        preview = transcript_result.transcript_text[:max_chars].strip()
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + "..."
    return preview
