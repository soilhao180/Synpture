from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LinkSample:
    sample_id: str
    url: str
    platform_hint: str | None = None
    title_hint: str | None = None
    notes: str = ""
    cookies_profile: str | None = None


@dataclass
class LinkProbe:
    normalized_url: str
    platform: str
    extractor_key: str | None = None
    title: str | None = None
    duration_seconds: float | None = None
    subtitle_languages: list[str] = field(default_factory=list)
    auto_caption_languages: list[str] = field(default_factory=list)


@dataclass
class AttemptArtifact:
    kind: str
    path: Path


@dataclass
class LinkAttempt:
    method: str
    status: str
    detail: str
    started_at: str
    finished_at: str
    requires_cookies: bool = False
    error_type: str | None = None
    text_length: int = 0
    artifacts: list[AttemptArtifact] = field(default_factory=list)


@dataclass
class LinkIngestResult:
    sample_id: str
    url: str
    normalized_url: str
    platform: str
    extractor_key: str | None
    title: str | None
    success: bool
    final_method: str | None
    final_text_length: int
    requires_cookies: bool
    support_evidence: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    attempts: list[LinkAttempt] = field(default_factory=list)
    artifacts: list[AttemptArtifact] = field(default_factory=list)
    run_dir: Path | None = None


@dataclass
class PlatformReport:
    platform: str
    sample_count: int
    success_count: int
    success_rate: float
    requires_cookies_count: int
    support_level: str
    top_methods: list[str] = field(default_factory=list)
    top_failure_reasons: list[str] = field(default_factory=list)
