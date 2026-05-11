from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.domain.job import JobStatus


TimelineValue = float | None
EntryType = Literal["local_media", "share_link", "text_file", "pasted_text"]
ContentType = Literal["video", "audio", "subtitle", "document", "plain_text", "url"]
AcquisitionMode = Literal[
    "media_transcription",
    "share_link_media_download",
    "subtitle_parse",
    "document_text_extract",
    "direct_text",
]


@dataclass
class InputSource:
    source_id: str
    entry_type: EntryType
    content_type: ContentType
    display_name: str
    original_filename: str | None = None
    mime_type: str | None = None
    local_path: Path | None = None
    text_content: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TranscriptSegment:
    index: int
    start: TimelineValue
    end: TimelineValue
    text: str


@dataclass
class TranscriptChunk:
    index: int
    start: TimelineValue
    end: TimelineValue
    text: str
    segments: list[TranscriptSegment] = field(default_factory=list)


@dataclass
class AcquisitionResult:
    source: InputSource
    acquisition_mode: AcquisitionMode
    display_text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    artifacts: dict[str, Path] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    failure_reason: str | None = None


@dataclass
class TranscriptBundle:
    source: InputSource
    acquisition: AcquisitionResult
    output_dir: Path
    backend_used: str
    model_used: str
    language: str
    transcript_text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    chunks: list[TranscriptChunk] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    intermediate_files: dict[str, Path] = field(default_factory=dict)
    chunks_written: bool = False
    gpu_diagnostics: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TranscriptResult:
    video_path: Path
    audio_path: Path
    output_dir: Path
    backend_used: str
    model_used: str
    language: str
    transcript_text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    chunks: list[TranscriptChunk] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    intermediate_files: dict[str, Path] = field(default_factory=dict)
    chunks_written: bool = False
    gpu_diagnostics: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ChunkSummary:
    index: int
    start: TimelineValue
    end: TimelineValue
    title: str
    summary: str
    key_points: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)


@dataclass
class StructuredSummary:
    provider: str
    model: str
    overall_summary: str
    key_points: list[str]
    action_items: list[str]
    chunk_summaries: list[ChunkSummary]
    warning: str | None = None


@dataclass
class LowValueSegment:
    start: TimelineValue
    end: TimelineValue
    reason: str
    excerpt: str


@dataclass
class DraftParagraphLabel:
    index: int
    text: str
    value_level: str
    reason: str = ""


@dataclass
class FirstPassResult:
    provider: str
    model: str
    cleaned_transcript: str
    one_line_verdict: str
    headline_verdict: str
    value_rating: str
    value_reason: str
    high_value_points: list[str]
    objective_context: list[str]
    low_value_segments: list[LowValueSegment]
    raw_transcript_reference: str
    draft_paragraphs: list[DraftParagraphLabel] = field(default_factory=list)
    uncertainty_notes: list[str] = field(default_factory=list)
    needs_human_check_timestamps: list[str] = field(default_factory=list)
    generated_title: str | None = None
    warning: str | None = None


@dataclass
class TemplateSection:
    title: str
    summary: str
    bullets: list[str] = field(default_factory=list)


@dataclass
class TemplateResult:
    template_id: str
    template_name: str
    provider: str
    model: str
    overview: str
    key_points: list[str]
    section_summaries: list[TemplateSection]
    template_fields: dict[str, Any] = field(default_factory=dict)
    warning: str | None = None


@dataclass
class TemplateDefinition:
    id: str
    name: str
    description: str
    input_fields: list[str]
    output_fields: list[str]
    prompt_instructions: str
    fallback_rules: dict[str, Any] = field(default_factory=dict)
    directory: Path | None = None


@dataclass
class PipelineStatus:
    stage_key: str
    stage_label: str
    progress_percent: int
    detail: str
    updated_at: str
    worker_pid: int | None = None
    last_heartbeat_at: str | None = None
    last_segment_at: str | None = None
    gpu_memory_used_mb: int | None = None
    active_chunk_index: int | None = None
    active_chunk_total: int | None = None


@dataclass
class TestResult:
    ok: bool
    kind: str
    message: str
    raw_preview: str | None = None
    request_summary: str | None = None
    status_code: int | None = None
    model_name: str | None = None
    models: list[str] = field(default_factory=list)


@dataclass
class RunListItem:
    run_dir: Path
    title: str
    entry_type: str
    state: str
    recovery_state: str
    updated_at: str
    progress_percent: int
    has_first_pass: bool
    has_templates: bool


@dataclass
class RunArtifacts:
    transcript_bundle: TranscriptBundle
    first_pass_result: FirstPassResult | None
    template_results: dict[str, TemplateResult]
    transcript_path: Path
    segments_path: Path
    chunks_path: Path | None = None
    input_source_path: Path | None = None
    acquisition_result_path: Path | None = None
    gpu_diagnostics_json_path: Path | None = None
    gpu_diagnostics_md_path: Path | None = None
    first_pass_json_path: Path | None = None
    first_pass_markdown_path: Path | None = None
    template_json_paths: dict[str, Path] = field(default_factory=dict)
    template_markdown_paths: dict[str, Path] = field(default_factory=dict)
    status_history: list[PipelineStatus | JobStatus] = field(default_factory=list)
    summary_input_preview: str | None = None
    failed_stage: str | None = None
    error_message: str | None = None
    selected_summary_model: str | None = None
    selected_transcribe_model: str | None = None
    active_template_id: str | None = None

    @property
    def transcript_result(self) -> TranscriptBundle:
        return self.transcript_bundle
