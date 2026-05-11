from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from src.application.status import JobStatusTracker, StatusCallback
from src.config import Settings
from src.domain.errors import AppError, ensure_app_error
from src.domain.job import JobRequest
from src.infrastructure.artifact_store import ArtifactStore, LocalArtifactStore
from src.models import RunArtifacts, TranscriptBundle
from src.services import AcquisitionService, SummaryService, TranscriptionService


class PipelineOrchestrator:
    def __init__(
        self,
        settings: Settings,
        *,
        artifact_store: ArtifactStore | None = None,
        acquisition_service: AcquisitionService | None = None,
        transcription_service: TranscriptionService | None = None,
        summary_service: SummaryService | None = None,
    ) -> None:
        self.settings = settings
        self.artifact_store = artifact_store or LocalArtifactStore(settings.output_dir)
        self.acquisition_service = acquisition_service or AcquisitionService()
        self.transcription_service = transcription_service or TranscriptionService()
        self.summary_service = summary_service or SummaryService()

    def run(self, request: JobRequest, progress_callback: StatusCallback | None = None) -> RunArtifacts:
        effective_settings = self._settings_for_request(request)
        job_id = self._build_job_id(request)
        source_label = self._resolve_source_label(request)
        run_dir = self.artifact_store.create_run(job_id, source_label, request=request)
        tracker = JobStatusTracker(
            job_id=job_id,
            callback=progress_callback,
            manifest_writer=self.artifact_store.record_status,
            run_dir=run_dir,
        )
        tracker.publish(
            state="running",
            phase="input",
            progress_percent=5,
            message="已创建处理任务。",
        )

        try:
            acquisition_outcome = self.acquisition_service.acquire(
                request,
                run_dir,
                effective_settings,
                progress_hook=lambda detail: tracker.publish(
                    state="running",
                    phase="acquisition",
                    progress_percent=10,
                    message=detail,
                ),
            )
            tracker.publish(
                state="running",
                phase="acquisition",
                progress_percent=15,
                message=f"已完成输入获取：{acquisition_outcome.acquisition.source.display_name}",
            )
            self.artifact_store.write_input_source(
                run_dir,
                self._build_pre_transcript_bundle(
                    acquisition_outcome.acquisition,
                    run_dir,
                    effective_settings,
                ),
            )

            tracker.publish(
                state="running",
                phase="chunking",
                progress_percent=55,
                message="正在整理分段与 chunks。",
            )
            transcript_bundle = self.transcription_service.build_transcript_bundle(
                acquisition_outcome.acquisition,
                run_dir,
                effective_settings,
                progress_hook=tracker.publish_legacy,
            )

            tracker.publish(
                state="running",
                phase="artifact_write",
                progress_percent=60,
                message="正在写出 transcript / segments / chunks。",
            )
            input_source_path, acquisition_result_path = self.artifact_store.write_input_source(run_dir, transcript_bundle)
            transcript_path, segments_path, chunks_path, gpu_json_path, gpu_md_path = self.artifact_store.write_transcript_bundle(
                run_dir,
                transcript_bundle,
                source_result=acquisition_outcome.source_result,
            )
            transcript_bundle.intermediate_files.update(
                {
                    "input_source": input_source_path,
                    "acquisition_result": acquisition_result_path,
                    "transcript": transcript_path,
                    "segments": segments_path,
                    "chunks": chunks_path,
                    **({"gpu_diagnostics_json": gpu_json_path} if gpu_json_path else {}),
                    **({"gpu_diagnostics_md": gpu_md_path} if gpu_md_path else {}),
                }
            )

            active_summary_model = request.summary_model or effective_settings.summary_api_model
            tracker.publish(
                state="running",
                phase="first_pass",
                progress_percent=78,
                message=f"正在生成第一稿标准底稿：{active_summary_model}",
            )
            try:
                first_pass_result = self.summary_service.run_first_pass(
                    transcript_bundle,
                    effective_settings,
                    summary_model_override=request.summary_model,
                )
            except Exception as exc:
                app_error = ensure_app_error(
                    exc,
                    default_code="summary.first_pass_failed",
                    default_message="第一稿标准底稿生成失败",
                )
                tracker.publish_failure(
                    app_error,
                    phase="first_pass",
                    progress_percent=78,
                    message=app_error.message,
                )
                return self._build_failure_artifacts(
                    run_dir,
                    tracker,
                    effective_settings,
                    failed_stage="first_pass",
                    error=app_error,
                    selected_summary_model=active_summary_model,
                )

            tracker.publish(
                state="running",
                phase="artifact_write",
                progress_percent=94,
                message="正在写出 first_pass.json 和 first_pass.md。",
            )
            self.artifact_store.write_first_pass(run_dir, first_pass_result, transcript_bundle)
            tracker.publish(
                state="succeeded",
                phase="artifact_write",
                progress_percent=100,
                message="第一稿标准底稿生成完成。",
            )
            return self._finalize_artifacts(
                run_dir,
                tracker,
                effective_settings,
                selected_summary_model=active_summary_model,
                selected_transcribe_model=transcript_bundle.model_used,
            )
        except Exception as exc:
            app_error = ensure_app_error(
                exc,
                default_code="system.unexpected",
                default_message="处理流程失败",
            )
            tracker.publish_failure(
                app_error,
                phase="artifact_write",
                progress_percent=100,
                message=app_error.message,
            )
            raise

    def resume_first_pass(
        self,
        run_dir: Path,
        progress_callback: StatusCallback | None = None,
        *,
        summary_model_override: str | None = None,
    ) -> RunArtifacts:
        artifacts = self.artifact_store.load_run(run_dir, self.settings)
        tracker = JobStatusTracker(
            job_id=self._build_recovery_job_id(run_dir),
            callback=progress_callback,
            manifest_writer=self.artifact_store.record_status,
            run_dir=run_dir,
        )
        tracker.publish(
            state="recoverable",
            phase="recovery",
            progress_percent=60,
            message="检测到 transcript / segments / chunks，继续恢复第一稿。",
        )
        active_summary_model = summary_model_override or self.settings.summary_api_model
        try:
            first_pass_result = self.summary_service.run_first_pass(
                artifacts.transcript_bundle,
                self.settings,
                summary_model_override=summary_model_override,
            )
        except Exception as exc:
            app_error = ensure_app_error(
                exc,
                default_code="summary.first_pass_failed",
                default_message="第一稿标准底稿恢复失败",
            )
            tracker.publish_failure(
                app_error,
                phase="first_pass",
                progress_percent=78,
                message=app_error.message,
            )
            return self._build_failure_artifacts(
                run_dir,
                tracker,
                self.settings,
                failed_stage="first_pass",
                error=app_error,
                selected_summary_model=active_summary_model,
            )

        self.artifact_store.write_first_pass(run_dir, first_pass_result, artifacts.transcript_bundle)
        tracker.publish(
            state="succeeded",
            phase="artifact_write",
            progress_percent=100,
            message="第一稿恢复完成。",
        )
        return self._finalize_artifacts(
            run_dir,
            tracker,
            self.settings,
            selected_summary_model=active_summary_model,
            selected_transcribe_model=artifacts.transcript_bundle.model_used,
        )

    def run_template(
        self,
        run_dir: Path,
        template_id: str,
        progress_callback: StatusCallback | None = None,
        *,
        summary_model_override: str | None = None,
    ) -> RunArtifacts:
        artifacts = self.artifact_store.load_run(run_dir, self.settings)
        if artifacts.first_pass_result is None:
            raise AppError(
                error_code="artifact.recovery_invalid",
                message="当前运行目录缺少第一稿，无法直接生成模板。",
                detail=str(run_dir),
            )

        tracker = JobStatusTracker(
            job_id=self._build_recovery_job_id(run_dir),
            callback=progress_callback,
            manifest_writer=self.artifact_store.record_status,
            run_dir=run_dir,
        )
        active_summary_model = summary_model_override or self.settings.summary_api_model
        tracker.publish(
            state="running",
            phase="template_pass",
            progress_percent=88,
            message=f"正在生成第二轮模板：{template_id}",
        )
        try:
            template_result = self.summary_service.run_template_pass(
                artifacts.first_pass_result,
                template_id,
                self.settings,
                summary_model_override=summary_model_override,
            )
        except Exception as exc:
            app_error = ensure_app_error(
                exc,
                default_code="summary.template_failed",
                default_message="第二轮模板生成失败",
            )
            tracker.publish_failure(
                app_error,
                phase="template_pass",
                progress_percent=88,
                message=app_error.message,
            )
            raise

        self.artifact_store.write_template_result(
            run_dir,
            template_result,
            artifacts.first_pass_result,
            artifacts.transcript_bundle,
        )
        tracker.publish(
            state="succeeded",
            phase="artifact_write",
            progress_percent=100,
            message=f"模板 {template_id} 生成完成。",
        )
        finalized = self._finalize_artifacts(
            run_dir,
            tracker,
            self.settings,
            selected_summary_model=active_summary_model,
            selected_transcribe_model=artifacts.transcript_bundle.model_used,
        )
        finalized.active_template_id = template_id
        return finalized

    def load_run(self, run_dir: Path) -> RunArtifacts:
        return self.artifact_store.load_run(run_dir, self.settings)

    def detect_recovery_state(self, run_dir: Path) -> str:
        return self.artifact_store.detect_recovery_state(run_dir)

    def find_resume_candidate(self, output_root: Path, current_run_dir: str | None = None) -> dict[str, str] | None:
        candidates = sorted(
            [item for item in output_root.iterdir() if item.is_dir()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            if current_run_dir and str(candidate) == current_run_dir:
                continue
            try:
                state = self.detect_recovery_state(candidate)
            except Exception:
                continue
            return {"run_dir": str(candidate), "state": state}
        return None

    def materialize_uploaded_project_directory(self, uploaded_files) -> Path:
        return self.artifact_store.materialize_uploaded_project_directory(uploaded_files, self.settings)

    def build_result_file_map(self, artifacts: RunArtifacts) -> dict[str, Path]:
        return self.artifact_store.build_result_file_map(artifacts)

    def run_gpu_diagnostic(self, request: JobRequest, progress_callback: StatusCallback | None = None) -> dict[str, object]:
        effective_settings = self._settings_for_request(request)
        job_id = self._build_job_id(request)
        source_label = self._resolve_source_label(request)
        run_dir = self.artifact_store.create_run(job_id, f"{source_label}_gpu_diag", request=request)
        tracker = JobStatusTracker(
            job_id=job_id,
            callback=progress_callback,
            manifest_writer=self.artifact_store.record_status,
            run_dir=run_dir,
        )
        acquisition_outcome = self.acquisition_service.acquire(request, run_dir, effective_settings)
        transcript_bundle = self.transcription_service.build_transcript_bundle(
            acquisition_outcome.acquisition,
            run_dir,
            effective_settings,
            progress_hook=tracker.publish_legacy,
        )
        tracker.publish(
            state="succeeded",
            phase="artifact_write",
            progress_percent=100,
            message=f"GPU 自检完成：{source_label}",
        )
        return {
            "chunk_count": len(transcript_bundle.chunks),
            "notes": transcript_bundle.notes,
            "diagnostics": transcript_bundle.gpu_diagnostics,
            "segment_count": len(transcript_bundle.segments),
            "language": transcript_bundle.language,
            "status_history": tracker.history,
        }

    def _settings_for_request(self, request: JobRequest) -> Settings:
        local_gpu_only = self.settings.local_gpu_only
        if request.entry_type in {"local_media", "share_link"}:
            local_gpu_only = True
        return replace(
            self.settings,
            transcribe_backend=request.transcribe_backend or self.settings.transcribe_backend,
            local_gpu_only=local_gpu_only,
        )

    def _build_job_id(self, request: JobRequest) -> str:
        parts = [request.entry_type]
        if "file_name" in request.payload:
            parts.append(str(request.payload.get("file_name") or ""))
        if "share_url" in request.payload:
            parts.append(str(request.payload.get("share_url") or ""))
        if "text" in request.payload:
            text = str(request.payload.get("text") or "")
            parts.append(text[:200])
            parts.append(str(len(text)))
        if "file_bytes" in request.payload:
            payload = request.payload.get("file_bytes")
            if isinstance(payload, bytes):
                parts.append(str(len(payload)))
                parts.append(hashlib.sha1(payload[:1024]).hexdigest())
        digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]
        return f"{request.entry_type}-{digest}"

    def _build_recovery_job_id(self, run_dir: Path) -> str:
        digest = hashlib.sha1(str(run_dir).encode("utf-8")).hexdigest()[:10]
        return f"recovery-{digest}"

    def _resolve_source_label(self, request: JobRequest) -> str:
        if request.entry_type in {"local_media", "text_file"}:
            return str(request.payload.get("file_name") or request.entry_type)
        if request.entry_type == "share_link":
            return str(request.payload.get("share_url") or "share_link")
        return request.entry_type

    def _build_pre_transcript_bundle(
        self,
        acquisition,
        run_dir: Path,
        settings: Settings,
    ) -> TranscriptBundle:
        return TranscriptBundle(
            source=acquisition.source,
            acquisition=acquisition,
            output_dir=run_dir,
            backend_used=acquisition.acquisition_mode,
            model_used="pending",
            language=settings.local_whisper_language,
            transcript_text=acquisition.display_text,
            segments=acquisition.segments,
            chunks=[],
            notes=list(acquisition.notes),
        )

    def _build_failure_artifacts(
        self,
        run_dir: Path,
        tracker: JobStatusTracker,
        settings: Settings,
        *,
        failed_stage: str,
        error: AppError,
        selected_summary_model: str | None,
    ) -> RunArtifacts:
        artifacts = self.artifact_store.load_run(run_dir, settings)
        artifacts.status_history = list(tracker.history)
        artifacts.failed_stage = failed_stage
        artifacts.error_message = error.detail or error.message
        artifacts.selected_summary_model = selected_summary_model
        artifacts.selected_transcribe_model = artifacts.transcript_bundle.model_used
        return artifacts

    def _finalize_artifacts(
        self,
        run_dir: Path,
        tracker: JobStatusTracker,
        settings: Settings,
        *,
        selected_summary_model: str | None,
        selected_transcribe_model: str | None,
    ) -> RunArtifacts:
        artifacts = self.artifact_store.load_run(run_dir, settings)
        artifacts.status_history = list(tracker.history)
        artifacts.selected_summary_model = selected_summary_model
        artifacts.selected_transcribe_model = selected_transcribe_model
        return artifacts
