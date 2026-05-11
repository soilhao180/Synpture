from __future__ import annotations

from pathlib import Path
from typing import Any


class YtDlpClient:
    def __init__(
        self,
        *,
        cookies_file: Path | None = None,
        cookies_from_browser: str | None = None,
        subtitle_languages: list[str] | None = None,
    ) -> None:
        self.cookies_file = cookies_file
        self.cookies_from_browser = cookies_from_browser
        self.subtitle_languages = subtitle_languages or ["zh-Hans", "zh-CN", "zh", "en"]

    def extract_info(self, url: str) -> dict[str, Any]:
        with self._create_ydl({"skip_download": True}) as ydl:
            return ydl.extract_info(url, download=False)

    def download_subtitles(
        self,
        *,
        url: str,
        output_dir: Path,
        automatic: bool,
        available_languages: list[str],
    ) -> tuple[Path | None, str | None]:
        language = _select_language(available_languages, self.subtitle_languages)
        if not language:
            return None, None

        prefix = "auto_subtitle" if automatic else "subtitle"
        options: dict[str, Any] = {
            "skip_download": True,
            "outtmpl": str(output_dir / f"{prefix}.%(ext)s"),
            "subtitleslangs": [language],
            "subtitlesformat": "vtt/best",
        }
        if automatic:
            options["writeautomaticsub"] = True
        else:
            options["writesubtitles"] = True

        with self._create_ydl(options) as ydl:
            ydl.extract_info(url, download=True)

        candidates = sorted(output_dir.glob(f"{prefix}*"), key=lambda item: item.stat().st_mtime, reverse=True)
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() not in {".part", ".ytdl"}:
                return candidate, language
        return None, language

    def download_media(self, *, url: str, output_dir: Path, media_kind: str) -> Path:
        if media_kind == "audio":
            options = {
                "format": "bestaudio/best",
                "outtmpl": str(output_dir / "audio.%(ext)s"),
            }
            prefix = "audio"
        elif media_kind == "video":
            options = {
                "format": "bv*+ba/best",
                "merge_output_format": "mp4",
                "outtmpl": str(output_dir / "video.%(ext)s"),
            }
            prefix = "video"
        else:
            raise ValueError(f"Unsupported media_kind: {media_kind}")

        with self._create_ydl(options) as ydl:
            ydl.extract_info(url, download=True)

        candidates = sorted(output_dir.glob(f"{prefix}*"), key=lambda item: item.stat().st_mtime, reverse=True)
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() not in {".part", ".ytdl"}:
                return candidate
        raise RuntimeError(f"yt-dlp completed but no {media_kind} file was found.")

    def _create_ydl(self, options: dict[str, Any]):
        yt_dlp = _import_yt_dlp()
        merged_options: dict[str, Any] = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
        }
        if self.cookies_file:
            merged_options["cookiefile"] = str(self.cookies_file)
        if self.cookies_from_browser:
            merged_options["cookiesfrombrowser"] = (self.cookies_from_browser,)
        merged_options.update(options)
        return yt_dlp.YoutubeDL(merged_options)


def _select_language(available_languages: list[str], preferred_languages: list[str]) -> str | None:
    normalized_map = {item.lower(): item for item in available_languages}
    for language in preferred_languages:
        candidate = normalized_map.get(language.lower())
        if candidate:
            return candidate
    return available_languages[0] if available_languages else None


def _import_yt_dlp():
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise RuntimeError("yt-dlp is not installed. Run `python -m pip install -r requirements.txt`.") from exc
    return yt_dlp
