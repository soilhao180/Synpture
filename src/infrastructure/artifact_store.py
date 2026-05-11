from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from src.artifacts import (
    load_acquisition_result,
    load_first_pass,
    load_input_source,
    load_template_result,
    persist_gpu_diagnostics,
    persist_source_artifacts,
    persist_transcript_artifacts,
    serialize_first_pass,
    serialize_template_result,
)
from src.config import Settings, load_settings
from src.domain.errors import AppError
from src.domain.job import JobRequest, JobStatus
from src.models import (
    AcquisitionResult,
    FirstPassResult,
    InputSource,
    RunListItem,
    RunArtifacts,
    TemplateResult,
    TranscriptBundle,
    TranscriptChunk,
    TranscriptSegment,
)
from src.progress import build_summary_input_preview
from src.result_writers import render_first_pass_markdown, render_template_markdown
from src.share_link_ingest import ShareLinkIngestResult
from src.template_registry import load_template_definition
from src.utils import build_run_directory, ensure_directory, timestamp_now, write_json, write_text


MANIFEST_FILENAME = "job.json"
MANIFEST_VERSION = 2


class ArtifactStore(ABC):
    @abstractmethod
    def create_run(self, job_id: str, source_label: str, *, request: JobRequest | None = None) -> Path:
        raise NotImplementedError

    @abstractmethod
    def record_status(self, run_dir: Path, status: JobStatus) -> None:
        raise NotImplementedError

    @abstractmethod
    def write_input_source(self, run_dir: Path, transcript_bundle: TranscriptBundle) -> tuple[Path, Path]:
        raise NotImplementedError

    @abstractmethod
    def write_transcript_bundle(
        self,
        run_dir: Path,
        transcript_bundle: TranscriptBundle,
        *,
        source_result: ShareLinkIngestResult | None = None,
    ) -> tuple[Path, Path, Path, Path | None, Path | None]:
        raise NotImplementedError

    @abstractmethod
    def write_first_pass(self, run_dir: Path, first_pass: FirstPassResult, transcript_bundle: TranscriptBundle) -> tuple[Path, Path]:
        raise NotImplementedError

    @abstractmethod
    def write_template_result(
        self,
        run_dir: Path,
        template_result: TemplateResult,
        first_pass: FirstPassResult,
        transcript_bundle: TranscriptBundle,
    ) -> tuple[Path, Path]:
        raise NotImplementedError

    @abstractmethod
    def load_run(self, run_dir: Path, settings: Settings | None = None) -> RunArtifacts:
        raise NotImplementedError

    @abstractmethod
    def detect_recovery_state(self, run_dir: Path) -> str:
        raise NotImplementedError

    @abstractmethod
    def build_result_file_map(self, artifacts: RunArtifacts) -> dict[str, Path]:
        raise NotImplementedError

    @abstractmethod
    def materialize_uploaded_project_directory(self, uploaded_files, settings: Settings) -> Path:
        raise NotImplementedError

    @abstractmethod
    def list_runs(self) -> list[RunListItem]:
        raise NotImplementedError


class LocalArtifactStore(ArtifactStore):
    def __init__(self, output_root: Path) -> None:
        self.output_root = ensure_directory(output_root)

    def create_run(self, job_id: str, source_label: str, *, request: JobRequest | None = None) -> Path:
        if request and request.requested_run_dir is not None:
            run_dir = ensure_directory(request.requested_run_dir)
        else:
            run_dir = build_run_directory(self.output_root, source_label)
        manifest = {
            "version": MANIFEST_VERSION,
            "job_id": job_id,
            "source_label": source_label,
            "entry_type": request.entry_type if request else None,
            "summary_model": request.summary_model if request else None,
            "transcribe_backend": request.transcribe_backend if request else None,
            "state": "pending",
            "phase": "input",
            "artifacts": {},
            "created_at": timestamp_now(),
            "updated_at": timestamp_now(),
        }
        write_json(run_dir / MANIFEST_FILENAME, manifest)
        return run_dir

    def record_status(self, run_dir: Path, status: JobStatus) -> None:
        manifest = self._load_manifest(run_dir)
        manifest["state"] = status.state
        manifest["phase"] = status.phase
        manifest["phase_label"] = status.phase_label
        manifest["progress_percent"] = status.progress_percent
        manifest["message"] = status.message
        manifest["error_code"] = status.error_code
        manifest["error_detail"] = status.error_detail
        manifest["updated_at"] = status.updated_at
        manifest["timestamps"] = status.timestamps
        manifest["metrics"] = status.metrics
        write_json(run_dir / MANIFEST_FILENAME, manifest)

    def write_input_source(self, run_dir: Path, transcript_bundle: TranscriptBundle) -> tuple[Path, Path]:
        input_source_path, acquisition_result_path = persist_source_artifacts(run_dir, transcript_bundle)
        self._update_artifacts(
            run_dir,
            input_source=str(input_source_path),
            acquisition_result=str(acquisition_result_path),
        )
        return input_source_path, acquisition_result_path

    def write_transcript_bundle(
        self,
        run_dir: Path,
        transcript_bundle: TranscriptBundle,
        *,
        source_result: ShareLinkIngestResult | None = None,
    ) -> tuple[Path, Path, Path, Path | None, Path | None]:
        transcript_path, segments_path, chunks_path = persist_transcript_artifacts(run_dir, transcript_bundle)
        transcript_bundle.intermediate_files.update(
            {
                "transcript": transcript_path,
                "segments": segments_path,
                "chunks": chunks_path,
            }
        )

        gpu_diagnostics_json_path = None
        gpu_diagnostics_md_path = None
        if transcript_bundle.gpu_diagnostics:
            gpu_diagnostics_json_path, gpu_diagnostics_md_path = persist_gpu_diagnostics(run_dir, transcript_bundle.gpu_diagnostics)
            transcript_bundle.intermediate_files.update(
                {
                    "gpu_diagnostics_json": gpu_diagnostics_json_path,
                    "gpu_diagnostics_md": gpu_diagnostics_md_path,
                }
            )

        if source_result is not None:
            share_link_ingest_path = write_json(
                run_dir / "share_link_ingest.json",
                {
                    "platform": source_result.platform,
                    "source_url": source_result.source_url,
                    "resolved_url": source_result.resolved_url,
                    "title": source_result.title,
                    "local_media_path": str(source_result.local_media_path),
                    "method": source_result.method,
                    "notes": source_result.notes,
                    "artifacts": {key: str(value) for key, value in source_result.artifacts.items()},
                },
            )
            transcript_bundle.intermediate_files["share_link_ingest"] = share_link_ingest_path

        self._update_artifacts(
            run_dir,
            transcript=str(transcript_path),
            segments=str(segments_path),
            chunks=str(chunks_path),
            gpu_diagnostics_json=str(gpu_diagnostics_json_path) if gpu_diagnostics_json_path else None,
            gpu_diagnostics_md=str(gpu_diagnostics_md_path) if gpu_diagnostics_md_path else None,
        )
        return transcript_path, segments_path, chunks_path, gpu_diagnostics_json_path, gpu_diagnostics_md_path

    def write_first_pass(self, run_dir: Path, first_pass: FirstPassResult, transcript_bundle: TranscriptBundle) -> tuple[Path, Path]:
        json_path = write_json(run_dir / "first_pass.json", serialize_first_pass(first_pass))
        markdown_path = write_text(
            run_dir / "first_pass.md",
            render_first_pass_markdown(first_pass, transcript_bundle),
        )
        self._update_artifacts(
            run_dir,
            first_pass_json=str(json_path),
            first_pass_md=str(markdown_path),
        )
        return json_path, markdown_path

    def write_template_result(
        self,
        run_dir: Path,
        template_result: TemplateResult,
        first_pass: FirstPassResult,
        transcript_bundle: TranscriptBundle,
    ) -> tuple[Path, Path]:
        template_definition = load_template_definition(template_result.template_id)
        json_path = write_json(run_dir / f"template_{template_result.template_id}.json", serialize_template_result(template_result))
        markdown_path = write_text(
            run_dir / f"template_{template_result.template_id}.md",
            render_template_markdown(
                template_result,
                first_pass,
                transcript_bundle,
                template_definition,
            ),
        )
        manifest = self._load_manifest(run_dir)
        template_artifacts = manifest.setdefault("template_artifacts", {})
        template_artifacts[template_result.template_id] = {
            "json": str(json_path),
            "markdown": str(markdown_path),
        }
        write_json(run_dir / MANIFEST_FILENAME, manifest)
        return json_path, markdown_path

    def load_run(self, run_dir: Path, settings: Settings | None = None) -> RunArtifacts:
        settings = settings or load_settings()
        (
            transcript_bundle,
            transcript_path,
            segments_path,
            chunks_path,
            input_source_path,
            acquisition_result_path,
            gpu_diagnostics_json_path,
            gpu_diagnostics_md_path,
        ) = self._load_transcript_bundle_from_run_dir(run_dir, settings)

        first_pass_json_path = run_dir / "first_pass.json"
        first_pass_markdown_path = run_dir / "first_pass.md"
        first_pass_result = load_first_pass(first_pass_json_path) if first_pass_json_path.exists() else None
        template_results, template_json_paths, template_markdown_paths = self._load_template_results_from_run_dir(run_dir)

        manifest = self._load_manifest(run_dir, create_if_missing=False)
        status_history = self._build_status_history(
            run_dir,
            manifest,
            transcript_bundle=transcript_bundle,
            has_first_pass=first_pass_result is not None,
            has_templates=bool(template_results),
        )

        return RunArtifacts(
            transcript_bundle=transcript_bundle,
            first_pass_result=first_pass_result,
            template_results=template_results,
            transcript_path=transcript_path,
            segments_path=segments_path,
            chunks_path=chunks_path,
            input_source_path=input_source_path,
            acquisition_result_path=acquisition_result_path,
            gpu_diagnostics_json_path=gpu_diagnostics_json_path,
            gpu_diagnostics_md_path=gpu_diagnostics_md_path,
            first_pass_json_path=first_pass_json_path if first_pass_json_path.exists() else None,
            first_pass_markdown_path=first_pass_markdown_path if first_pass_markdown_path.exists() else None,
            template_json_paths=template_json_paths,
            template_markdown_paths=template_markdown_paths,
            status_history=status_history,
            summary_input_preview=build_summary_input_preview(transcript_bundle),
            selected_summary_model=str(manifest.get("summary_model")) if manifest and manifest.get("summary_model") else settings.summary_api_model,
            selected_transcribe_model=transcript_bundle.model_used,
            active_template_id=next(reversed(template_results)) if template_results else None,
        )

    def detect_recovery_state(self, run_dir: Path) -> str:
        transcript_ready = (run_dir / "transcript.txt").exists() and (run_dir / "chunks.json").exists()
        first_pass_ready = (run_dir / "first_pass.json").exists()
        template_jsons = list(run_dir.glob("template_*.json"))
        if transcript_ready and not first_pass_ready:
            return "transcript_only"
        if first_pass_ready and not template_jsons:
            return "first_pass_only"
        if first_pass_ready and template_jsons:
            return "partial_templates"
        raise AppError(
            error_code="artifact.recovery_invalid",
            message="目录缺少恢复所需的核心产物",
            detail=str(run_dir),
        )

    def build_result_file_map(self, artifacts: RunArtifacts) -> dict[str, Path]:
        file_map: dict[str, Path] = {
            "transcript.txt": artifacts.transcript_path,
            "segments.json": artifacts.segments_path,
        }
        if artifacts.chunks_path:
            file_map["chunks.json"] = artifacts.chunks_path
        if artifacts.input_source_path:
            file_map["input_source.json"] = artifacts.input_source_path
        if artifacts.acquisition_result_path:
            file_map["acquisition_result.json"] = artifacts.acquisition_result_path
        if artifacts.gpu_diagnostics_json_path:
            file_map["gpu_diagnostics.json"] = artifacts.gpu_diagnostics_json_path
        if artifacts.gpu_diagnostics_md_path:
            file_map["gpu_diagnostics.md"] = artifacts.gpu_diagnostics_md_path
        if artifacts.first_pass_json_path:
            file_map["first_pass.json"] = artifacts.first_pass_json_path
        if artifacts.first_pass_markdown_path:
            file_map["first_pass.md"] = artifacts.first_pass_markdown_path
        for template_id, path in artifacts.template_json_paths.items():
            file_map[f"template_{template_id}.json"] = path
        for template_id, path in artifacts.template_markdown_paths.items():
            file_map[f"template_{template_id}.md"] = path
        return file_map

    def materialize_uploaded_project_directory(self, uploaded_files, settings: Settings) -> Path:
        restore_root = ensure_directory(settings.output_dir / "restored_projects")
        first_name = Path(uploaded_files[0].name)
        root_label = first_name.parts[0] if len(first_name.parts) > 1 else first_name.stem or "restored_project"
        restore_dir = build_run_directory(restore_root, root_label)

        for uploaded in uploaded_files:
            relative_path = Path(uploaded.name)
            parts = relative_path.parts
            if len(parts) > 1:
                relative_path = Path(*parts[1:])
            target_path = restore_dir / relative_path
            ensure_directory(target_path.parent)
            target_path.write_bytes(uploaded.getvalue())

        child_dirs = [item for item in restore_dir.iterdir() if item.is_dir()]
        if len(child_dirs) == 1 and not (restore_dir / "transcript.txt").exists():
            candidate = child_dirs[0]
            if (candidate / "transcript.txt").exists() or (candidate / "first_pass.json").exists():
                return candidate
        return restore_dir

    def list_runs(self) -> list[RunListItem]:
        items: list[RunListItem] = []
        for run_dir in self._discover_run_directories():
            item = self._build_run_list_item(run_dir)
            if item is not None:
                items.append(item)
        return sorted(items, key=lambda item: (item.updated_at, str(item.run_dir)), reverse=True)

    def _load_manifest(self, run_dir: Path, *, create_if_missing: bool = True) -> dict[str, Any]:
        manifest_path = run_dir / MANIFEST_FILENAME
        if manifest_path.exists():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        if not create_if_missing:
            return {}
        manifest = {
            "version": MANIFEST_VERSION,
            "artifacts": {},
            "created_at": timestamp_now(),
            "updated_at": timestamp_now(),
        }
        write_json(manifest_path, manifest)
        return manifest

    def _update_artifacts(self, run_dir: Path, **artifacts: str | None) -> None:
        manifest = self._load_manifest(run_dir)
        artifact_map = manifest.setdefault("artifacts", {})
        for key, value in artifacts.items():
            if value is not None:
                artifact_map[key] = value
        manifest["updated_at"] = timestamp_now()
        write_json(run_dir / MANIFEST_FILENAME, manifest)

    def _load_transcript_bundle_from_run_dir(
        self,
        run_dir: Path,
        settings: Settings,
    ) -> tuple[TranscriptBundle, Path, Path, Path, Path | None, Path | None, Path | None, Path | None]:
        transcript_path = run_dir / "transcript.txt"
        segments_path = run_dir / "segments.json"
        chunks_path = run_dir / "chunks.json"
        input_source_path = run_dir / "input_source.json"
        acquisition_result_path = run_dir / "acquisition_result.json"
        gpu_diagnostics_json_path = run_dir / "gpu_diagnostics.json"
        gpu_diagnostics_md_path = run_dir / "gpu_diagnostics.md"

        transcript_text = transcript_path.read_text(encoding="utf-8")
        segments_payload = json.loads(segments_path.read_text(encoding="utf-8"))
        chunks_payload = json.loads(chunks_path.read_text(encoding="utf-8"))
        segments = self._load_segments(segments_payload.get("segments", []))
        chunks = self._load_chunks(chunks_payload.get("chunks", []))

        if input_source_path.exists():
            source = load_input_source(input_source_path)
        else:
            source = self._infer_input_source(run_dir)

        if acquisition_result_path.exists():
            acquisition = load_acquisition_result(acquisition_result_path, source)
        else:
            acquisition = self._infer_acquisition_result(run_dir, source, transcript_text, segments)

        gpu_entries: list[dict] = []
        if gpu_diagnostics_json_path.exists():
            gpu_entries = list(json.loads(gpu_diagnostics_json_path.read_text(encoding="utf-8")).get("entries", []))

        notes = list(acquisition.notes)
        if source.entry_type in {"local_media", "share_link"}:
            notes.insert(0, f"本次本地转录模型：{settings.whisper_cpp_model_path.name}")
        transcript_bundle = TranscriptBundle(
            source=source,
            acquisition=acquisition,
            output_dir=run_dir,
            backend_used=self._infer_backend_used(source, acquisition),
            model_used=self._infer_model_used(source, settings),
            language=settings.local_whisper_language,
            transcript_text=transcript_text,
            segments=segments,
            chunks=chunks,
            notes=notes,
            intermediate_files={
                "transcript": transcript_path,
                "segments": segments_path,
                "chunks": chunks_path,
                **({"input_source": input_source_path} if input_source_path.exists() else {}),
                **({"acquisition_result": acquisition_result_path} if acquisition_result_path.exists() else {}),
                **({"gpu_diagnostics_json": gpu_diagnostics_json_path} if gpu_diagnostics_json_path.exists() else {}),
                **({"gpu_diagnostics_md": gpu_diagnostics_md_path} if gpu_diagnostics_md_path.exists() else {}),
            },
            chunks_written=True,
            gpu_diagnostics=gpu_entries,
        )
        return (
            transcript_bundle,
            transcript_path,
            segments_path,
            chunks_path,
            input_source_path if input_source_path.exists() else None,
            acquisition_result_path if acquisition_result_path.exists() else None,
            gpu_diagnostics_json_path if gpu_diagnostics_json_path.exists() else None,
            gpu_diagnostics_md_path if gpu_diagnostics_md_path.exists() else None,
        )

    def _load_segments(self, payload: list[dict]) -> list[TranscriptSegment]:
        return [
            TranscriptSegment(
                index=int(item.get("index", index)),
                start=float(item["start"]) if item.get("start") is not None else None,
                end=float(item["end"]) if item.get("end") is not None else None,
                text=str(item.get("text", "")),
            )
            for index, item in enumerate(payload, start=1)
        ]

    def _load_chunks(self, payload: list[dict]) -> list[TranscriptChunk]:
        return [
            TranscriptChunk(
                index=int(item.get("index", index)),
                start=float(item["start"]) if item.get("start") is not None else None,
                end=float(item["end"]) if item.get("end") is not None else None,
                text=str(item.get("text", "")),
            )
            for index, item in enumerate(payload, start=1)
        ]

    def _infer_input_source(self, run_dir: Path) -> InputSource:
        share_link_path = run_dir / "share_link_ingest.json"
        if share_link_path.exists():
            payload = json.loads(share_link_path.read_text(encoding="utf-8"))
            return InputSource(
                source_id="share_link",
                entry_type="share_link",
                content_type="url",
                display_name=str(payload.get("title") or payload.get("platform") or "分享链接"),
                url=str(payload.get("source_url") or ""),
                metadata={
                    "platform": payload.get("platform"),
                    "resolved_url": payload.get("resolved_url"),
                    "share_link_method": payload.get("method"),
                },
                local_path=Path(str(payload.get("local_media_path"))) if payload.get("local_media_path") else None,
            )

        source_media_dir = run_dir / "source_media"
        media_files = sorted(source_media_dir.glob("*")) if source_media_dir.exists() else []
        if media_files:
            media_path = media_files[0]
            return InputSource(
                source_id=media_path.stem,
                entry_type="local_media",
                content_type="video",
                display_name=media_path.name,
                original_filename=media_path.name,
                local_path=media_path,
                metadata={"extension": media_path.suffix.lower()},
            )

        return InputSource(
            source_id=run_dir.name,
            entry_type="text_file",
            content_type="plain_text",
            display_name=run_dir.name,
        )

    def _infer_acquisition_result(
        self,
        run_dir: Path,
        source: InputSource,
        transcript_text: str,
        segments: list[TranscriptSegment],
    ) -> AcquisitionResult:
        share_link_path = run_dir / "share_link_ingest.json"
        if share_link_path.exists():
            payload = json.loads(share_link_path.read_text(encoding="utf-8"))
            notes = [str(item) for item in payload.get("notes", []) if str(item).strip()]
            return AcquisitionResult(
                source=source,
                acquisition_mode="share_link_media_download",
                display_text=transcript_text,
                segments=segments,
                artifacts={"downloaded_media": source.local_path} if source.local_path else {},
                notes=["入口类型：share_link", "取文方式：分享链接取媒体后本地转录", *notes],
            )

        if source.entry_type == "local_media":
            return AcquisitionResult(
                source=source,
                acquisition_mode="media_transcription",
                display_text=transcript_text,
                segments=segments,
                artifacts={"input_media": source.local_path} if source.local_path else {},
                notes=["入口类型：local_media", "取文方式：媒体转录"],
            )

        return AcquisitionResult(
            source=source,
            acquisition_mode="direct_text",
            display_text=transcript_text,
            segments=segments,
            notes=[f"入口类型：{source.entry_type}", "取文方式：直接文本输入"],
        )

    def _infer_backend_used(self, source: InputSource, acquisition: AcquisitionResult) -> str:
        if source.entry_type in {"local_media", "share_link"}:
            return "local-gpu-only"
        return acquisition.acquisition_mode

    def _infer_model_used(self, source: InputSource, settings: Settings) -> str:
        if source.entry_type in {"local_media", "share_link"}:
            return settings.whisper_cpp_model_path.name
        return "text-input"

    def _load_template_results_from_run_dir(self, run_dir: Path) -> tuple[dict[str, TemplateResult], dict[str, Path], dict[str, Path]]:
        template_results: dict[str, TemplateResult] = {}
        template_json_paths: dict[str, Path] = {}
        template_markdown_paths: dict[str, Path] = {}
        for template_json_path in sorted(run_dir.glob("template_*.json")):
            template_result = load_template_result(template_json_path)
            template_results[template_result.template_id] = template_result
            template_json_paths[template_result.template_id] = template_json_path
            markdown_path = run_dir / f"{template_json_path.stem}.md"
            if markdown_path.exists():
                template_markdown_paths[template_result.template_id] = markdown_path
        return template_results, template_json_paths, template_markdown_paths

    def _discover_run_directories(self) -> list[Path]:
        if not self.output_root.exists():
            return []

        candidates: set[Path] = set()
        for pattern in (MANIFEST_FILENAME, "transcript.txt", "first_pass.json", "template_*.json"):
            for match in self.output_root.rglob(pattern):
                parent = match.parent
                if self._looks_like_run_dir(parent):
                    candidates.add(parent)
        return sorted(candidates)

    def _looks_like_run_dir(self, run_dir: Path) -> bool:
        if not run_dir.is_dir():
            return False
        required_markers = (
            run_dir / MANIFEST_FILENAME,
            run_dir / "transcript.txt",
            run_dir / "chunks.json",
            run_dir / "first_pass.json",
            run_dir / "input_source.json",
        )
        if any(marker.exists() for marker in required_markers):
            return True
        return any(run_dir.glob("template_*.json"))

    def _build_run_list_item(self, run_dir: Path) -> RunListItem | None:
        if not self._looks_like_run_dir(run_dir):
            return None

        manifest = self._load_manifest(run_dir, create_if_missing=False)
        recovery_state = self._safe_detect_recovery_state(run_dir)
        has_first_pass = (run_dir / "first_pass.json").exists()
        has_templates = any(run_dir.glob("template_*.json"))
        if recovery_state is None and not manifest:
            return None

        return RunListItem(
            run_dir=run_dir,
            title=self._infer_run_title(run_dir, manifest),
            entry_type=self._infer_run_entry_type(run_dir, manifest),
            state=self._infer_run_state(manifest, recovery_state, has_first_pass, has_templates),
            recovery_state=recovery_state or "unavailable",
            updated_at=self._infer_updated_at(run_dir, manifest),
            progress_percent=self._infer_progress_percent(manifest, recovery_state, has_first_pass, has_templates),
            has_first_pass=has_first_pass,
            has_templates=has_templates,
        )

    def _safe_detect_recovery_state(self, run_dir: Path) -> str | None:
        try:
            return self.detect_recovery_state(run_dir)
        except Exception:
            if any(run_dir.glob("template_*.json")):
                return "partial_templates"
            if (run_dir / "first_pass.json").exists():
                return "first_pass_only"
            if (run_dir / "transcript.txt").exists() and (run_dir / "chunks.json").exists():
                return "transcript_only"
            return None

    def _infer_run_title(self, run_dir: Path, manifest: dict[str, Any]) -> str:
        first_pass_path = run_dir / "first_pass.json"
        if first_pass_path.exists():
            try:
                payload = json.loads(first_pass_path.read_text(encoding="utf-8"))
                generated_title = str(payload.get("generated_title") or "").strip()
                if generated_title:
                    return generated_title
            except Exception:
                pass

        input_source_path = run_dir / "input_source.json"
        if input_source_path.exists():
            try:
                source = load_input_source(input_source_path)
                if source.display_name:
                    return source.display_name
            except Exception:
                pass
        source_label = str(manifest.get("source_label") or "").strip()
        if source_label:
            return source_label
        return run_dir.name

    def _infer_run_entry_type(self, run_dir: Path, manifest: dict[str, Any]) -> str:
        entry_type = str(manifest.get("entry_type") or "").strip()
        if entry_type:
            return entry_type
        input_source_path = run_dir / "input_source.json"
        if input_source_path.exists():
            try:
                return load_input_source(input_source_path).entry_type
            except Exception:
                pass
        return "unknown"

    def _infer_run_state(
        self,
        manifest: dict[str, Any],
        recovery_state: str | None,
        has_first_pass: bool,
        has_templates: bool,
    ) -> str:
        manifest_state = str(manifest.get("state") or "").strip()
        if manifest_state:
            return manifest_state
        if has_templates or has_first_pass:
            return "succeeded"
        if recovery_state:
            return "recoverable"
        return "unknown"

    def _infer_updated_at(self, run_dir: Path, manifest: dict[str, Any]) -> str:
        updated_at = str(manifest.get("updated_at") or manifest.get("created_at") or "").strip()
        if updated_at:
            return updated_at
        return datetime.fromtimestamp(run_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    def _infer_progress_percent(
        self,
        manifest: dict[str, Any],
        recovery_state: str | None,
        has_first_pass: bool,
        has_templates: bool,
    ) -> int:
        artifact_floor = 100 if has_templates else 92 if has_first_pass else 68 if recovery_state == "transcript_only" else 0
        raw_value = manifest.get("progress_percent")
        try:
            if raw_value is not None:
                return max(artifact_floor, min(100, int(raw_value)))
        except (TypeError, ValueError):
            pass
        if has_templates:
            return 100
        if has_first_pass:
            return 92
        if recovery_state == "transcript_only":
            return 68
        return 5

    def _build_status_history(
        self,
        run_dir: Path,
        manifest: dict[str, Any],
        *,
        transcript_bundle: TranscriptBundle,
        has_first_pass: bool,
        has_templates: bool,
    ) -> list[JobStatus]:
        updated_at = str(
            manifest.get("updated_at")
            or manifest.get("created_at")
            or datetime.fromtimestamp(run_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        )
        raw_state = str(manifest.get("state") or "").strip()
        raw_phase = str(manifest.get("phase") or "").strip()
        progress_percent = self._infer_progress_percent(
            manifest,
            self._safe_detect_recovery_state(run_dir),
            has_first_pass,
            has_templates,
        )

        phase = "template_pass"
        phase_label = "模板加工"
        message = "已完成模板加工，可继续查看结果或下载产物。"
        state = "succeeded"

        if has_first_pass and not has_templates:
            phase = "first_pass"
            phase_label = "第一稿整理"
            message = "已完成第一稿整理，可继续生成模板结果。"
        elif not has_first_pass:
            phase = "transcription"
            phase_label = "转录完成"
            message = "已完成转录，可继续生成第一稿。"
            state = "recoverable"

        if raw_phase in {"input", "acquisition", "transcription", "chunking", "first_pass", "template_pass", "artifact_write", "recovery"}:
            phase = raw_phase
        if raw_state in {"pending", "running", "succeeded", "failed", "recoverable"}:
            state = raw_state

        phase_labels = {
            "input": "输入准备",
            "acquisition": "内容采集",
            "transcription": "转录完成",
            "chunking": "内容切片",
            "first_pass": "第一稿整理",
            "template_pass": "模板加工",
            "artifact_write": "结果落盘",
            "recovery": "恢复任务",
        }
        phase_messages = {
            "input": "任务已创建，等待处理。",
            "acquisition": "正在解析来源与采集内容。",
            "transcription": f"已完成转录，来源：{transcript_bundle.source.display_name}",
            "chunking": "已完成切片，等待进入总结整理。",
            "first_pass": "已完成第一稿整理，可继续生成模板结果。",
            "template_pass": "已完成模板加工，可继续查看结果或下载产物。",
            "artifact_write": "结果已落盘，可继续查看与导出。",
            "recovery": "项目已恢复，可从当前阶段继续处理。",
        }
        phase_label = phase_labels.get(phase, phase_label)
        message = str(manifest.get("message") or phase_messages.get(phase) or message)

        return [
            JobStatus(
                job_id=str(manifest.get("job_id") or run_dir.name),
                state=state,  # type: ignore[arg-type]
                phase=phase,  # type: ignore[arg-type]
                progress_percent=progress_percent,
                message=message,
                error_code=manifest.get("error_code"),
                error_detail=manifest.get("error_detail"),
                metrics=dict(manifest.get("metrics") or {}),
                phase_label=phase_label,
                timestamps={
                    "updated_at": updated_at,
                    "created_at": str(manifest.get("created_at") or updated_at),
                    "started_at": str(manifest.get("created_at") or updated_at),
                    "finished_at": updated_at if state in {"succeeded", "failed"} else None,
                },
            )
        ]
