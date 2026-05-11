from __future__ import annotations

from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse, urlunparse

from src.link_ingest.models import AttemptArtifact, LinkAttempt, LinkIngestResult, LinkProbe, LinkSample
from src.link_ingest.platforms import detect_platform
from src.utils import ensure_directory, timestamp_now, write_json, write_text


class MetadataClient(Protocol):
    def extract_info(self, url: str) -> dict[str, object]:
        ...

    def download_subtitles(
        self,
        *,
        url: str,
        output_dir: Path,
        automatic: bool,
        available_languages: list[str],
    ) -> tuple[Path | None, str | None]:
        ...

    def download_media(self, *, url: str, output_dir: Path, media_kind: str) -> Path:
        ...


class MediaTranscriber(Protocol):
    def transcribe_media(self, media_path: Path, output_dir: Path) -> str:
        ...


class LinkIngestPipeline:
    def __init__(self, *, metadata_client: MetadataClient, transcriber: MediaTranscriber) -> None:
        self.metadata_client = metadata_client
        self.transcriber = transcriber

    def run_sample(self, sample: LinkSample, output_root: Path) -> LinkIngestResult:
        platform = detect_platform(sample.url, sample.platform_hint)
        run_dir = ensure_directory(output_root / sample.sample_id)
        write_json(
            run_dir / "sample.json",
            {
                "sample_id": sample.sample_id,
                "url": sample.url,
                "platform_hint": sample.platform_hint,
                "title_hint": sample.title_hint,
                "notes": sample.notes,
                "cookies_profile": sample.cookies_profile,
            },
        )

        attempts: list[LinkAttempt] = []
        artifacts: list[AttemptArtifact] = [AttemptArtifact(kind="sample", path=run_dir / "sample.json")]
        cookies_required_by_sample = bool(sample.cookies_profile)

        try:
            metadata = self.metadata_client.extract_info(sample.url)
        except Exception as exc:
            message = str(exc)
            attempt = _failed_attempt("metadata_probe", message)
            attempts.append(attempt)
            return LinkIngestResult(
                sample_id=sample.sample_id,
                url=sample.url,
                normalized_url=_normalize_url(sample.url),
                platform=platform,
                extractor_key=None,
                title=sample.title_hint,
                success=False,
                final_method=None,
                final_text_length=0,
                requires_cookies=_looks_like_cookies_issue(message),
                failure_reason=message,
                attempts=attempts,
                artifacts=artifacts,
                run_dir=run_dir,
            )

        probe = _build_probe(sample.url, sample.platform_hint, metadata)
        metadata_path = write_json(
            run_dir / "metadata.json",
            {
                "normalized_url": probe.normalized_url,
                "platform": probe.platform,
                "extractor_key": probe.extractor_key,
                "title": probe.title,
                "duration_seconds": probe.duration_seconds,
                "subtitle_languages": probe.subtitle_languages,
                "auto_caption_languages": probe.auto_caption_languages,
                "raw": metadata,
            },
        )
        artifacts.append(AttemptArtifact(kind="metadata", path=metadata_path))

        result: LinkIngestResult | None = None

        subtitle_summary = _build_subtitle_summary(probe)
        attempts.append(
            _skipped_attempt(
                "subtitle_paths_disabled",
                f"Subtitle paths are disabled by policy. {subtitle_summary}",
            )
        )

        method = "video_download_transcribe"
        attempt = _new_attempt(method, f"Trying {method}.")
        attempts.append(attempt)
        try:
            media_path = self.metadata_client.download_media(url=sample.url, output_dir=run_dir, media_kind="video")
            attempt.artifacts.append(AttemptArtifact(kind="video", path=media_path))
            text = self.transcriber.transcribe_media(media_path=media_path, output_dir=run_dir / method)
            text_path = write_text(run_dir / f"{method}.txt", text + ("\n" if text else ""))
            attempt.artifacts.append(AttemptArtifact(kind="text", path=text_path))
            if not text.strip():
                _finish_attempt(
                    attempt,
                    status="failed",
                    detail=f"{method} completed but produced empty transcript text.",
                    error_type="empty_text",
                )
            else:
                _finish_attempt(attempt, status="success", detail=f"{method} produced usable text.", text_length=len(text))
                result = LinkIngestResult(
                    sample_id=sample.sample_id,
                    url=sample.url,
                    normalized_url=probe.normalized_url,
                    platform=probe.platform,
                    extractor_key=probe.extractor_key,
                    title=probe.title or sample.title_hint,
                    success=True,
                    final_method=method,
                    final_text_length=len(text),
                    requires_cookies=cookies_required_by_sample,
                    support_evidence=[
                        "Unified ingest path used: download video, extract audio locally, then transcribe.",
                        subtitle_summary,
                        "Sample is annotated as cookies-backed." if cookies_required_by_sample else "No cookies annotation on sample.",
                    ],
                    attempts=attempts,
                    artifacts=artifacts + attempt.artifacts,
                    run_dir=run_dir,
                )
        except Exception as exc:
            message = str(exc)
            _finish_attempt(
                attempt,
                status="failed",
                detail=message,
                requires_cookies=_looks_like_cookies_issue(message),
                error_type=_classify_error(message),
            )

        if result is not None:
            return result

        requires_cookies = cookies_required_by_sample or any(attempt.requires_cookies for attempt in attempts)
        failure_reason = next((attempt.detail for attempt in reversed(attempts) if attempt.status == "failed"), "All methods failed.")
        return LinkIngestResult(
            sample_id=sample.sample_id,
            url=sample.url,
            normalized_url=probe.normalized_url,
            platform=probe.platform,
            extractor_key=probe.extractor_key,
            title=probe.title or sample.title_hint,
            success=False,
            final_method=None,
            final_text_length=0,
            requires_cookies=requires_cookies,
            failure_reason=failure_reason,
            attempts=attempts,
            artifacts=artifacts + [artifact for attempt in attempts for artifact in attempt.artifacts],
            run_dir=run_dir,
        )


def _build_probe(url: str, platform_hint: str | None, metadata: dict[str, object]) -> LinkProbe:
    subtitles = metadata.get("subtitles") or {}
    auto_captions = metadata.get("automatic_captions") or {}
    return LinkProbe(
        normalized_url=_normalize_url(str(metadata.get("webpage_url") or metadata.get("original_url") or url)),
        platform=detect_platform(str(metadata.get("webpage_url") or url), platform_hint),
        extractor_key=str(metadata.get("extractor_key") or "") or None,
        title=str(metadata.get("title") or "") or None,
        duration_seconds=float(metadata["duration"]) if metadata.get("duration") is not None else None,
        subtitle_languages=sorted(subtitles.keys()) if isinstance(subtitles, dict) else [],
        auto_caption_languages=sorted(auto_captions.keys()) if isinstance(auto_captions, dict) else [],
    )


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.params, parsed.query, ""))


def _new_attempt(method: str, detail: str) -> LinkAttempt:
    now = timestamp_now()
    return LinkAttempt(method=method, status="running", detail=detail, started_at=now, finished_at=now)


def _finish_attempt(
    attempt: LinkAttempt,
    *,
    status: str,
    detail: str,
    requires_cookies: bool = False,
    error_type: str | None = None,
    text_length: int = 0,
) -> None:
    attempt.status = status
    attempt.detail = detail
    attempt.finished_at = timestamp_now()
    attempt.requires_cookies = requires_cookies
    attempt.error_type = error_type
    attempt.text_length = text_length


def _skipped_attempt(method: str, detail: str) -> LinkAttempt:
    now = timestamp_now()
    return LinkAttempt(method=method, status="skipped", detail=detail, started_at=now, finished_at=now)


def _failed_attempt(method: str, detail: str) -> LinkAttempt:
    now = timestamp_now()
    return LinkAttempt(
        method=method,
        status="failed",
        detail=detail,
        started_at=now,
        finished_at=now,
        requires_cookies=_looks_like_cookies_issue(detail),
        error_type=_classify_error(detail),
    )


def _looks_like_cookies_issue(message: str) -> bool:
    lowered = message.lower()
    keywords = ["cookie", "cookies", "login", "sign in", "private", "账号", "登录", "验证"]
    return any(keyword in lowered for keyword in keywords)


def _classify_error(message: str) -> str:
    lowered = message.lower()
    if _looks_like_cookies_issue(message):
        return "cookies_required"
    if "geo" in lowered or "region" in lowered:
        return "geo_restricted"
    if "404" in lowered or "not found" in lowered:
        return "not_found"
    if "timed out" in lowered or "connection" in lowered or "network" in lowered:
        return "network"
    if "extractor" in lowered or "unsupported" in lowered:
        return "extractor"
    return "unknown"


def _build_subtitle_summary(probe: LinkProbe) -> str:
    original_count = len(probe.subtitle_languages)
    automatic_count = len(probe.auto_caption_languages)
    if original_count == 0 and automatic_count == 0:
        return "No subtitle or automatic caption tracks were exposed by metadata."
    return (
        "Metadata exposed subtitle tracks but they were intentionally ignored "
        f"(original={original_count}, automatic={automatic_count})."
    )
