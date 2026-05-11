from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from src.application import PipelineOrchestrator
from src.config import Settings, load_settings
from src.domain.job import JobRequest, JobStatus
from src.models import PipelineStatus, RunArtifacts
from src.progress import build_status


ProgressCallback = Callable[[PipelineStatus], None]


def run_local_media_pipeline(
    file_name: str,
    file_bytes: bytes,
    transcribe_backend: str,
    progress_callback: ProgressCallback,
    *,
    summary_model_override: str | None = None,
    run_dir: Path | None = None,
) -> RunArtifacts:
    settings = _build_settings(transcribe_backend=transcribe_backend, local_gpu_only=True)
    orchestrator = PipelineOrchestrator(settings)
    request = JobRequest(
        entry_type="local_media",
        payload={"file_name": file_name, "file_bytes": file_bytes},
        summary_model=summary_model_override,
        transcribe_backend=transcribe_backend,
        requested_run_dir=run_dir,
    )
    return _run_with_legacy_progress(orchestrator, request, progress_callback)


def run_share_link_pipeline(
    share_url: str,
    transcribe_backend: str,
    progress_callback: ProgressCallback,
    *,
    browser_profiles: dict[str, str | None],
    summary_model_override: str | None = None,
    run_dir: Path | None = None,
) -> RunArtifacts:
    settings = _build_settings(transcribe_backend=transcribe_backend, local_gpu_only=True)
    orchestrator = PipelineOrchestrator(settings)
    request = JobRequest(
        entry_type="share_link",
        payload={"share_url": share_url},
        summary_model=summary_model_override,
        transcribe_backend=transcribe_backend,
        browser_profiles=browser_profiles,
        requested_run_dir=run_dir,
    )
    return _run_with_legacy_progress(orchestrator, request, progress_callback)


def run_text_file_pipeline(
    file_name: str,
    file_bytes: bytes,
    progress_callback: ProgressCallback,
    *,
    summary_model_override: str | None = None,
    run_dir: Path | None = None,
) -> RunArtifacts:
    settings = load_settings()
    orchestrator = PipelineOrchestrator(settings)
    request = JobRequest(
        entry_type="text_file",
        payload={"file_name": file_name, "file_bytes": file_bytes},
        summary_model=summary_model_override,
        requested_run_dir=run_dir,
    )
    return _run_with_legacy_progress(orchestrator, request, progress_callback)


def run_pasted_text_pipeline(
    text: str,
    progress_callback: ProgressCallback,
    *,
    summary_model_override: str | None = None,
    run_dir: Path | None = None,
) -> RunArtifacts:
    settings = load_settings()
    orchestrator = PipelineOrchestrator(settings)
    request = JobRequest(
        entry_type="pasted_text",
        payload={"text": text},
        summary_model=summary_model_override,
        requested_run_dir=run_dir,
    )
    return _run_with_legacy_progress(orchestrator, request, progress_callback)


def run_gpu_diagnostic_pipeline(
    file_name: str,
    file_bytes: bytes,
    progress_callback: ProgressCallback,
) -> dict[str, object]:
    settings = _build_settings(transcribe_backend="local", local_gpu_only=True)
    orchestrator = PipelineOrchestrator(settings)
    request = JobRequest(
        entry_type="local_media",
        payload={"file_name": file_name, "file_bytes": file_bytes},
        transcribe_backend="local",
    )
    result = orchestrator.run_gpu_diagnostic(request, _legacy_callback_adapter(progress_callback))
    return result


def load_run_artifacts(run_dir: Path, settings: Settings | None = None) -> RunArtifacts:
    orchestrator = PipelineOrchestrator(settings or load_settings())
    artifacts = orchestrator.load_run(run_dir)
    if not artifacts.status_history:
        artifacts.status_history = [_job_status_to_pipeline_status(_completed_status(run_dir))]
    return artifacts


def resume_first_pass_from_run_dir(
    run_dir: Path,
    progress_callback: ProgressCallback,
    *,
    summary_model_override: str | None = None,
) -> RunArtifacts:
    orchestrator = PipelineOrchestrator(load_settings())
    artifacts = orchestrator.resume_first_pass(
        run_dir,
        _legacy_callback_adapter(progress_callback),
        summary_model_override=summary_model_override,
    )
    return artifacts


def resume_template_pass_from_run_dir(
    run_dir: Path,
    template_id: str,
    progress_callback: ProgressCallback,
    *,
    summary_model_override: str | None = None,
) -> RunArtifacts:
    orchestrator = PipelineOrchestrator(load_settings())
    return orchestrator.run_template(
        run_dir,
        template_id,
        _legacy_callback_adapter(progress_callback),
        summary_model_override=summary_model_override,
    )


def find_resume_candidate(output_root: Path, current_run_dir: str | None = None) -> dict[str, str] | None:
    orchestrator = PipelineOrchestrator(load_settings())
    return orchestrator.find_resume_candidate(output_root, current_run_dir)


def find_resume_candidate_for_run_dir(run_dir: Path) -> str:
    orchestrator = PipelineOrchestrator(load_settings())
    return orchestrator.detect_recovery_state(run_dir)


def materialize_uploaded_project_directory(uploaded_files, settings: Settings) -> Path:
    orchestrator = PipelineOrchestrator(settings)
    return orchestrator.materialize_uploaded_project_directory(uploaded_files)


def _run_with_legacy_progress(
    orchestrator: PipelineOrchestrator,
    request: JobRequest,
    progress_callback: ProgressCallback,
) -> RunArtifacts:
    artifacts = orchestrator.run(request, _legacy_callback_adapter(progress_callback))
    artifacts.status_history = [_job_status_to_pipeline_status(status) for status in artifacts.status_history]
    return artifacts


def _legacy_callback_adapter(progress_callback: ProgressCallback | None) -> Callable[[JobStatus], None] | None:
    if progress_callback is None:
        return None

    def _callback(status: JobStatus) -> None:
        progress_callback(_job_status_to_pipeline_status(status))

    return _callback


def _job_status_to_pipeline_status(status: JobStatus) -> PipelineStatus:
    return PipelineStatus(
        stage_key=status.phase,
        stage_label=status.phase_label or status.phase,
        progress_percent=status.progress_percent,
        detail=status.message if not status.error_code else f"[{status.error_code}] {status.message}",
        updated_at=status.updated_at,
        worker_pid=status.worker_pid,
        last_heartbeat_at=status.last_heartbeat_at,
        last_segment_at=status.last_segment_at,
        gpu_memory_used_mb=status.gpu_memory_used_mb,
        active_chunk_index=status.active_chunk_index,
        active_chunk_total=status.active_chunk_total,
    )


def _completed_status(run_dir: Path) -> JobStatus:
    return JobStatus(
        job_id=f"loaded-{run_dir.name}",
        state="succeeded",
        phase="artifact_write",
        progress_percent=100,
        message="已从本地目录加载现有结果。",
        phase_label="处理完成",
    )


def _build_settings(*, transcribe_backend: str, local_gpu_only: bool) -> Settings:
    return replace(load_settings(), transcribe_backend=transcribe_backend, local_gpu_only=local_gpu_only)
