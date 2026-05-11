from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.domain.errors import AppError
from src.domain.job import JobPhase, JobStatus
from src.utils import timestamp_now


StatusCallback = Callable[[JobStatus], None]

PHASE_LABELS: dict[JobPhase, str] = {
    "input": "任务创建",
    "acquisition": "取文准备",
    "transcription": "转录处理中",
    "chunking": "整理分段",
    "first_pass": "生成首轮底稿",
    "template_pass": "生成模板结果",
    "artifact_write": "写出产物",
    "recovery": "恢复任务",
}

LEGACY_STAGE_META: dict[str, tuple[JobPhase, int, str]] = {
    "task_created": ("input", 5, "任务已创建"),
    "video_saved": ("acquisition", 10, "输入已准备"),
    "extracting_audio": ("transcription", 25, "正在提取音频"),
    "transcribing": ("transcription", 45, "正在执行转录"),
    "chunking": ("chunking", 55, "正在整理分段"),
    "transcript_written": ("artifact_write", 60, "已写出转录产物"),
    "first_pass": ("first_pass", 78, "正在生成首轮底稿"),
    "template_pass": ("template_pass", 88, "正在生成模板结果"),
    "rendering_markdown": ("artifact_write", 94, "正在写出 Markdown"),
    "completed": ("artifact_write", 100, "处理完成"),
}


@dataclass
class JobStatusTracker:
    job_id: str
    callback: StatusCallback | None = None
    manifest_writer: Callable[[Path, JobStatus], None] | None = None
    run_dir: Path | None = None
    created_at: str = field(default_factory=timestamp_now)
    history: list[JobStatus] = field(default_factory=list)

    def publish(
        self,
        *,
        state: str,
        phase: JobPhase,
        progress_percent: int,
        message: str,
        error_code: str | None = None,
        error_detail: str | None = None,
        metrics: dict | None = None,
        phase_label: str | None = None,
    ) -> JobStatus:
        updated_at = timestamp_now()
        timestamps = {
            "created_at": self.created_at,
            "started_at": self.created_at if state in {"running", "succeeded", "failed"} else None,
            "updated_at": updated_at,
            "finished_at": updated_at if state in {"succeeded", "failed"} else None,
        }
        status = JobStatus(
            job_id=self.job_id,
            state=state,  # type: ignore[arg-type]
            phase=phase,
            progress_percent=progress_percent,
            message=message,
            error_code=error_code,
            error_detail=error_detail,
            timestamps=timestamps,
            metrics=dict(metrics or {}),
            phase_label=phase_label or PHASE_LABELS.get(phase, phase),
        )
        self.history.append(status)
        if self.run_dir is not None and self.manifest_writer is not None:
            self.manifest_writer(self.run_dir, status)
        if self.callback is not None:
            self.callback(status)
        return status

    def publish_legacy(self, stage_key: str, detail: str, extra: dict | None = None) -> JobStatus:
        phase, progress_percent, phase_label = LEGACY_STAGE_META.get(stage_key, ("artifact_write", 0, stage_key))
        state = "succeeded" if stage_key == "completed" else "running"
        return self.publish(
            state=state,
            phase=phase,
            progress_percent=progress_percent,
            message=detail,
            metrics=extra,
            phase_label=phase_label,
        )

    def publish_failure(self, error: AppError, *, phase: JobPhase, progress_percent: int, message: str, metrics: dict | None = None) -> JobStatus:
        return self.publish(
            state="failed",
            phase=phase,
            progress_percent=progress_percent,
            message=message,
            error_code=error.error_code,
            error_detail=error.detail or str(error),
            metrics=metrics,
            phase_label=PHASE_LABELS.get(phase, phase),
        )
