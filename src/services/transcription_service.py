from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.config import Settings
from src.domain.errors import AppError
from src.models import AcquisitionResult, InputSource, TranscriptBundle, TranscriptResult, TranscriptSegment
from src.segmenter import build_chunks
from src.transcriber import transcribe_video


LegacyProgressHook = Callable[[str, str, dict | None], None]


class TranscriptionService:
    def build_transcript_bundle(
        self,
        acquisition: AcquisitionResult,
        run_dir: Path,
        settings: Settings,
        *,
        progress_hook: LegacyProgressHook | None = None,
    ) -> TranscriptBundle:
        if acquisition.acquisition_mode in {"media_transcription", "share_link_media_download"}:
            media_path = next(
                (path for key, path in acquisition.artifacts.items() if key in {"input_media", "downloaded_media"}),
                None,
            )
            if media_path is None:
                raise AppError(
                    error_code="transcription.worker_failed",
                    message="媒体转录缺少可处理文件",
                )
            try:
                transcript_result = transcribe_video(
                    media_path,
                    run_dir,
                    settings,
                    progress_hook=progress_hook,
                )
            except Exception as exc:
                raise self._map_error(exc) from exc
            return self._convert_legacy_transcript(
                legacy_result=transcript_result,
                source=acquisition.source,
                acquisition=acquisition,
            )

        transcript_text = acquisition.display_text.strip()
        segments = acquisition.segments or [TranscriptSegment(index=1, start=None, end=None, text=transcript_text)]
        chunks = build_chunks(
            segments=segments,
            max_minutes=settings.chunk_max_minutes,
            gap_seconds=settings.chunk_gap_seconds,
        )
        return TranscriptBundle(
            source=acquisition.source,
            acquisition=acquisition,
            output_dir=run_dir,
            backend_used=acquisition.acquisition_mode,
            model_used="text-input",
            language=settings.local_whisper_language,
            transcript_text=transcript_text,
            segments=segments,
            chunks=chunks,
            notes=list(acquisition.notes),
        )

    def _convert_legacy_transcript(
        self,
        *,
        legacy_result: TranscriptResult,
        source: InputSource,
        acquisition: AcquisitionResult,
    ) -> TranscriptBundle:
        notes = list(legacy_result.notes)
        for note in acquisition.notes:
            if note not in notes:
                notes.append(note)
        return TranscriptBundle(
            source=source,
            acquisition=acquisition,
            output_dir=legacy_result.output_dir,
            backend_used=legacy_result.backend_used,
            model_used=legacy_result.model_used,
            language=legacy_result.language,
            transcript_text=legacy_result.transcript_text,
            segments=legacy_result.segments,
            chunks=legacy_result.chunks,
            notes=notes,
            intermediate_files=dict(legacy_result.intermediate_files),
            chunks_written=legacy_result.chunks_written,
            gpu_diagnostics=legacy_result.gpu_diagnostics,
        )

    def _map_error(self, exc: Exception) -> AppError:
        text = str(exc)
        lowered = text.lower()
        if "未找到" in text and ("ffmpeg" in lowered or "whisper.cpp" in lowered):
            return AppError(
                error_code="transcription.binary_missing",
                message="本地转录依赖缺失",
                detail=text,
            )
        if "模型文件" in text:
            return AppError(
                error_code="transcription.model_missing",
                message="本地转录模型缺失",
                detail=text,
            )
        if "gpu-only" in lowered or "worker" in lowered:
            return AppError(
                error_code="transcription.worker_failed",
                message="本地转录执行失败",
                detail=text,
            )
        return AppError(
            error_code="transcription.worker_failed",
            message="转录失败",
            detail=text,
        )
