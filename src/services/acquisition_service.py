from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.config import Settings
from src.domain.errors import AppError, ensure_app_error
from src.domain.job import JobRequest
from src.link_ingest.platforms import detect_platform
from src.models import AcquisitionResult
from src.share_link_ingest import ShareLinkIngestResult
from src.source_ingest import (
    acquire_local_media,
    acquire_pasted_text,
    acquire_share_link,
    acquire_text_file,
    create_local_media_source,
    create_pasted_text_source,
    create_share_link_source,
    create_text_file_source,
)


ProgressHook = Callable[[str], None]


@dataclass
class AcquisitionOutcome:
    acquisition: AcquisitionResult
    source_result: ShareLinkIngestResult | None = None


class AcquisitionService:
    def acquire(
        self,
        request: JobRequest,
        run_dir: Path,
        settings: Settings,
        *,
        progress_hook: ProgressHook | None = None,
    ) -> AcquisitionOutcome:
        try:
            if request.entry_type == "local_media":
                return self._acquire_local_media(request, run_dir)
            if request.entry_type == "text_file":
                return self._acquire_text_file(request, run_dir)
            if request.entry_type == "pasted_text":
                return self._acquire_pasted_text(request, run_dir)
            if request.entry_type == "share_link":
                return self._acquire_share_link(request, run_dir, settings, progress_hook=progress_hook)
            raise AppError(
                error_code="input.unsupported_type",
                message="不支持的输入类型",
                detail=request.entry_type,
            )
        except AppError:
            raise
        except Exception as exc:
            raise self._map_error(request, exc) from exc

    def _acquire_local_media(self, request: JobRequest, run_dir: Path) -> AcquisitionOutcome:
        file_name = str(request.payload.get("file_name") or "").strip()
        file_bytes = request.payload.get("file_bytes")
        if not file_name or not isinstance(file_bytes, bytes):
            raise AppError(
                error_code="input.unsupported_type",
                message="本地媒体输入不完整",
                detail="缺少 file_name 或 file_bytes",
            )
        source, _ = create_local_media_source(file_name=file_name, file_bytes=file_bytes, run_dir=run_dir)
        return AcquisitionOutcome(acquisition=acquire_local_media(source))

    def _acquire_text_file(self, request: JobRequest, run_dir: Path) -> AcquisitionOutcome:
        file_name = str(request.payload.get("file_name") or "").strip()
        file_bytes = request.payload.get("file_bytes")
        if not file_name or not isinstance(file_bytes, bytes):
            raise AppError(
                error_code="input.unsupported_type",
                message="文本文件输入不完整",
                detail="缺少 file_name 或 file_bytes",
            )
        source, _ = create_text_file_source(file_name=file_name, file_bytes=file_bytes, run_dir=run_dir)
        return AcquisitionOutcome(acquisition=acquire_text_file(source))

    def _acquire_pasted_text(self, request: JobRequest, run_dir: Path) -> AcquisitionOutcome:
        text = str(request.payload.get("text") or "")
        if not text.strip():
            raise AppError(
                error_code="input.empty_text",
                message="粘贴文本不能为空",
            )
        source = create_pasted_text_source(text=text)
        return AcquisitionOutcome(acquisition=acquire_pasted_text(source, run_dir))

    def _acquire_share_link(
        self,
        request: JobRequest,
        run_dir: Path,
        settings: Settings,
        *,
        progress_hook: ProgressHook | None = None,
    ) -> AcquisitionOutcome:
        share_url = str(request.payload.get("share_url") or "").strip()
        if not share_url:
            raise AppError(
                error_code="input.invalid_url",
                message="分享链接不能为空",
            )

        platform = detect_platform(share_url)
        if platform == "unknown":
            raise AppError(
                error_code="input.invalid_url",
                message="无法识别分享链接平台",
                detail=share_url,
            )
        if platform == "douyin" and not request.browser_profiles.get("douyin"):
            raise AppError(
                error_code="acquisition.share_link_auth_required",
                message="抖音分享链接需要先完成工具内授权",
            )

        source = create_share_link_source(share_url=share_url)
        acquisition, source_result = acquire_share_link(
            source=source,
            run_dir=run_dir,
            settings=settings,
            browser_profiles=request.browser_profiles,
            progress_hook=progress_hook,
        )
        return AcquisitionOutcome(acquisition=acquisition, source_result=source_result)

    def _map_error(self, request: JobRequest, exc: Exception) -> AppError:
        text = str(exc)
        if request.entry_type == "share_link":
            if "授权" in text or "登录" in text:
                return AppError(
                    error_code="acquisition.share_link_auth_required",
                    message="分享链接需要工具内授权",
                    detail=text,
                )
            return AppError(
                error_code="acquisition.download_failed",
                message="分享链接取文失败",
                detail=text,
            )
        if request.entry_type == "pasted_text":
            return AppError(
                error_code="input.empty_text",
                message="粘贴文本处理失败",
                detail=text,
            )
        if request.entry_type == "text_file" and Path(str(request.payload.get("file_name") or "")).suffix.lower() in {".srt", ".vtt"}:
            return AppError(
                error_code="acquisition.subtitle_parse_failed",
                message="字幕解析失败",
                detail=text,
            )
        return ensure_app_error(
            exc,
            default_code="input.unsupported_type",
            default_message="输入处理失败",
        )
