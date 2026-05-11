from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Callable

from src.config import Settings
from src.link_ingest.platforms import detect_platform
from src.link_ingest.subtitles import parse_subtitle_file
from src.models import AcquisitionResult, InputSource, TranscriptSegment
from src.share_link_ingest import ShareLinkIngestResult, ingest_share_link
from src.utils import ensure_directory, normalize_whitespace, slugify_filename, write_text


ProgressHook = Callable[[str], None]

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".flv"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}
TEXT_EXTENSIONS = {".txt", ".md", ".docx", ".srt", ".vtt"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".json3", ".srv1", ".srv2", ".srv3", ".ttml", ".xml"}


def create_local_media_source(
    *,
    file_name: str,
    file_bytes: bytes,
    run_dir: Path,
) -> tuple[InputSource, Path]:
    suffix = Path(file_name).suffix.lower()
    content_type = classify_media_content_type(file_name)
    if content_type is None:
        raise RuntimeError("该文件不是受支持的本地媒体，请改到“文本输入”Tab 上传文本或字幕文件。")

    media_dir = ensure_directory(run_dir / "source_media")
    local_path = media_dir / file_name
    local_path.write_bytes(file_bytes)
    source = InputSource(
        source_id=slugify_filename(local_path.stem),
        entry_type="local_media",
        content_type=content_type,
        display_name=local_path.name,
        original_filename=file_name,
        mime_type=_mime_hint_from_suffix(suffix),
        local_path=local_path,
        metadata={"extension": suffix},
    )
    return source, local_path


def create_text_file_source(
    *,
    file_name: str,
    file_bytes: bytes,
    run_dir: Path,
) -> tuple[InputSource, Path]:
    suffix = Path(file_name).suffix.lower()
    if suffix not in TEXT_EXTENSIONS and suffix not in SUBTITLE_EXTENSIONS:
        raise RuntimeError("文本入口首版只支持 txt、md、docx、srt、vtt。")

    content_type = classify_text_content_type(file_name)
    input_dir = ensure_directory(run_dir / "source_text")
    local_path = input_dir / file_name
    local_path.write_bytes(file_bytes)
    source = InputSource(
        source_id=slugify_filename(local_path.stem),
        entry_type="text_file",
        content_type=content_type,
        display_name=local_path.name,
        original_filename=file_name,
        mime_type=_mime_hint_from_suffix(suffix),
        local_path=local_path,
        metadata={"extension": suffix},
    )
    return source, local_path


def create_pasted_text_source(*, text: str) -> InputSource:
    cleaned = text.strip()
    if not cleaned:
        raise RuntimeError("粘贴文本不能为空。")
    return InputSource(
        source_id="pasted_text",
        entry_type="pasted_text",
        content_type="plain_text",
        display_name="粘贴文本",
        text_content=cleaned,
        metadata={"char_count": len(cleaned)},
    )


def create_share_link_source(*, share_url: str) -> InputSource:
    url = share_url.strip()
    if not url:
        raise RuntimeError("分享链接不能为空。")
    platform = detect_platform(url)
    return InputSource(
        source_id=slugify_filename(platform),
        entry_type="share_link",
        content_type="url",
        display_name=f"{platform} 分享链接",
        url=url,
        metadata={"platform": platform},
    )


def acquire_local_media(source: InputSource) -> AcquisitionResult:
    if source.local_path is None:
        raise RuntimeError("本地媒体源缺少本地文件路径。")
    return AcquisitionResult(
        source=source,
        acquisition_mode="media_transcription",
        display_text="",
        artifacts={"input_media": source.local_path},
        notes=[f"入口类型：{source.entry_type}", "取文方式：媒体转录"],
    )


def acquire_share_link(
    *,
    source: InputSource,
    run_dir: Path,
    settings: Settings,
    browser_profiles: dict[str, str | None],
    progress_hook: ProgressHook | None = None,
) -> tuple[AcquisitionResult, ShareLinkIngestResult]:
    if not source.url:
        raise RuntimeError("分享链接源缺少 URL。")

    ingest_result = ingest_share_link(
        share_url=source.url,
        run_dir=run_dir,
        settings=settings,
        browser_profiles=browser_profiles,
        progress_hook=progress_hook,
    )
    source.display_name = ingest_result.title or source.display_name
    source.metadata.update(
        {
            "platform": ingest_result.platform,
            "resolved_url": ingest_result.resolved_url,
            "share_link_method": ingest_result.method,
        }
    )
    acquisition = AcquisitionResult(
        source=source,
        acquisition_mode="share_link_media_download",
        display_text="",
        artifacts={"downloaded_media": ingest_result.local_media_path, **ingest_result.artifacts},
        notes=[
            f"入口类型：{source.entry_type}",
            "取文方式：分享链接取媒体后本地转录",
            *ingest_result.notes,
        ],
    )
    return acquisition, ingest_result


def acquire_text_file(source: InputSource) -> AcquisitionResult:
    if source.local_path is None:
        raise RuntimeError("文本文件源缺少本地文件路径。")
    suffix = source.local_path.suffix.lower()

    if suffix in SUBTITLE_EXTENSIONS:
        display_text, segments = parse_subtitle_file(source.local_path)
        return AcquisitionResult(
            source=source,
            acquisition_mode="subtitle_parse",
            display_text=display_text,
            segments=segments,
            artifacts={"source_text": source.local_path},
            notes=[f"入口类型：{source.entry_type}", "取文方式：字幕解析"],
        )

    if suffix == ".docx":
        text = _extract_docx_text(source.local_path)
        paragraphs = _split_into_paragraphs(text)
        segments = _paragraphs_to_segments(paragraphs)
        return AcquisitionResult(
            source=source,
            acquisition_mode="document_text_extract",
            display_text="\n\n".join(paragraphs),
            segments=segments,
            artifacts={"source_text": source.local_path},
            notes=[f"入口类型：{source.entry_type}", "取文方式：文档提纯文本"],
        )

    text = _decode_text_bytes(source.local_path.read_bytes())
    paragraphs = _split_into_paragraphs(text)
    segments = _paragraphs_to_segments(paragraphs)
    return AcquisitionResult(
        source=source,
        acquisition_mode="direct_text",
        display_text="\n\n".join(paragraphs),
        segments=segments,
        artifacts={"source_text": source.local_path},
        notes=[f"入口类型：{source.entry_type}", "取文方式：直接文本输入"],
    )


def acquire_pasted_text(source: InputSource, run_dir: Path) -> AcquisitionResult:
    text = source.text_content or ""
    paragraphs = _split_into_paragraphs(text)
    display_text = "\n\n".join(paragraphs)
    text_dir = ensure_directory(run_dir / "source_text")
    text_path = write_text(text_dir / "pasted_text.txt", display_text + ("\n" if display_text else ""))
    return AcquisitionResult(
        source=source,
        acquisition_mode="direct_text",
        display_text=display_text,
        segments=_paragraphs_to_segments(paragraphs),
        artifacts={"source_text": text_path},
        notes=[f"入口类型：{source.entry_type}", "取文方式：粘贴文本"],
    )


def classify_media_content_type(file_name: str) -> str | None:
    suffix = Path(file_name).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return None


def classify_text_content_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix in SUBTITLE_EXTENSIONS:
        return "subtitle"
    if suffix == ".docx":
        return "document"
    return "plain_text"


def _decode_text_bytes(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk", "cp936", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _split_into_paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_paragraphs = re.split(r"\n\s*\n", normalized)
    paragraphs = [normalize_whitespace(item.replace("\n", " ")) for item in raw_paragraphs]
    return [item for item in paragraphs if item]


def _paragraphs_to_segments(paragraphs: list[str]) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(index=index, start=None, end=None, text=paragraph)
        for index, paragraph in enumerate(paragraphs, start=1)
    ]


def _extract_docx_text(path: Path) -> str:
    from docx import Document

    document = Document(BytesIO(path.read_bytes()))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text and paragraph.text.strip()]
    return "\n\n".join(paragraphs)


def _mime_hint_from_suffix(suffix: str) -> str | None:
    if suffix in VIDEO_EXTENSIONS:
        return "video/*"
    if suffix in AUDIO_EXTENSIONS:
        return "audio/*"
    if suffix in SUBTITLE_EXTENSIONS:
        return "text/subtitle"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".txt", ".md"}:
        return "text/plain"
    return None
