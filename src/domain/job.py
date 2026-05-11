from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.utils import timestamp_now


JobState = Literal["pending", "running", "succeeded", "failed", "recoverable"]
JobPhase = Literal[
    "input",
    "acquisition",
    "transcription",
    "chunking",
    "first_pass",
    "template_pass",
    "artifact_write",
    "recovery",
]


@dataclass
class JobRequest:
    entry_type: Literal["local_media", "share_link", "text_file", "pasted_text"]
    payload: dict[str, Any]
    summary_model: str | None = None
    transcribe_backend: str = "auto"
    template_id: str | None = None
    browser_profiles: dict[str, str | None] = field(default_factory=dict)
    requested_run_dir: Path | None = None


@dataclass
class JobStatus:
    job_id: str
    state: JobState
    phase: JobPhase
    progress_percent: int
    message: str
    error_code: str | None = None
    error_detail: str | None = None
    timestamps: dict[str, str | None] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    phase_label: str = ""

    def __post_init__(self) -> None:
        now = timestamp_now()
        self.timestamps.setdefault("updated_at", now)
        self.timestamps.setdefault("created_at", self.timestamps["updated_at"])
        self.timestamps.setdefault("started_at", self.timestamps["updated_at"] if self.state == "running" else None)
        if self.state in {"succeeded", "failed"}:
            self.timestamps.setdefault("finished_at", self.timestamps["updated_at"])
        else:
            self.timestamps.setdefault("finished_at", None)

    @property
    def updated_at(self) -> str:
        return self.timestamps.get("updated_at") or timestamp_now()

    @property
    def created_at(self) -> str | None:
        return self.timestamps.get("created_at")

    @property
    def started_at(self) -> str | None:
        return self.timestamps.get("started_at")

    @property
    def finished_at(self) -> str | None:
        return self.timestamps.get("finished_at")

    @property
    def worker_pid(self) -> int | None:
        value = self.metrics.get("worker_pid")
        return int(value) if isinstance(value, int) else None

    @property
    def last_heartbeat_at(self) -> str | None:
        value = self.metrics.get("last_heartbeat_at")
        return str(value) if value is not None else None

    @property
    def last_segment_at(self) -> str | None:
        value = self.metrics.get("last_segment_at")
        return str(value) if value is not None else None

    @property
    def gpu_memory_used_mb(self) -> int | None:
        value = self.metrics.get("gpu_memory_used_mb")
        return int(value) if isinstance(value, int) else None

    @property
    def active_chunk_index(self) -> int | None:
        value = self.metrics.get("active_chunk_index")
        return int(value) if isinstance(value, int) else None

    @property
    def active_chunk_total(self) -> int | None:
        value = self.metrics.get("active_chunk_total")
        return int(value) if isinstance(value, int) else None
