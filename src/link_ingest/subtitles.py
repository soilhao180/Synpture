from __future__ import annotations

import html
import json
import re
from pathlib import Path

from src.models import TranscriptSegment
from src.utils import dedupe_keep_order, normalize_whitespace


TIMESTAMP_RE = re.compile(
    r"^\s*(?P<start>(\d{2}:)?\d{2}:\d{2}([.,]\d{3})?)\s+-->\s+(?P<end>(\d{2}:)?\d{2}:\d{2}([.,]\d{3})?).*$"
)
TAG_RE = re.compile(r"<[^>]+>")


def extract_text_from_subtitle_file(path: Path) -> str:
    return parse_subtitle_file(path)[0]


def parse_subtitle_file(path: Path) -> tuple[str, list[TranscriptSegment]]:
    suffix = path.suffix.lower()
    if suffix == ".json3":
        return _parse_json3(path)
    if suffix in {".srv1", ".srv2", ".srv3", ".ttml", ".xml"}:
        return _parse_xml_like(path)
    if suffix in {".vtt", ".srt"}:
        return _parse_line_based(path)
    text = normalize_whitespace(path.read_text(encoding="utf-8", errors="replace"))
    return text, [TranscriptSegment(index=1, start=None, end=None, text=text)] if text else []


def _parse_line_based(path: Path) -> tuple[str, list[TranscriptSegment]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    text_lines: list[str] = []
    segments: list[TranscriptSegment] = []
    pending_start: float | None = None
    pending_end: float | None = None
    pending_parts: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_start, pending_end, pending_parts
        cleaned = normalize_whitespace(" ".join(part for part in pending_parts if part))
        if cleaned:
            text_lines.append(cleaned)
            segments.append(
                TranscriptSegment(
                    index=len(segments) + 1,
                    start=pending_start,
                    end=pending_end,
                    text=cleaned,
                )
            )
        pending_start = None
        pending_end = None
        pending_parts = []

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_pending()
            continue
        upper = line.upper()
        if upper == "WEBVTT" or upper.startswith("NOTE"):
            continue
        match = TIMESTAMP_RE.match(line)
        if match:
            flush_pending()
            pending_start = _parse_timestamp(match.group("start"))
            pending_end = _parse_timestamp(match.group("end"))
            continue
        if line.isdigit():
            continue
        cleaned = normalize_whitespace(html.unescape(TAG_RE.sub("", line)))
        if cleaned:
            pending_parts.append(cleaned)

    flush_pending()
    return "\n".join(dedupe_keep_order(text_lines)), segments


def _parse_json3(path: Path) -> tuple[str, list[TranscriptSegment]]:
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    events = payload.get("events", [])
    text_lines: list[str] = []
    segments: list[TranscriptSegment] = []
    for event in events:
        segments_payload = event.get("segs", [])
        if not isinstance(segments_payload, list):
            continue
        parts = [normalize_whitespace(html.unescape(str(item.get("utf8", "")))) for item in segments_payload]
        text = normalize_whitespace(" ".join(part for part in parts if part))
        if not text:
            continue
        start = _json3_ms_to_seconds(event.get("tStartMs"))
        duration = _json3_ms_to_seconds(event.get("dDurationMs"))
        end = start + duration if start is not None and duration is not None else None
        text_lines.append(text)
        segments.append(
            TranscriptSegment(
                index=len(segments) + 1,
                start=start,
                end=end,
                text=text,
            )
        )
    return "\n".join(dedupe_keep_order(text_lines)), segments


def _parse_xml_like(path: Path) -> tuple[str, list[TranscriptSegment]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    collected = re.findall(r">([^<]+)<", text)
    cleaned = [normalize_whitespace(html.unescape(item)) for item in collected]
    plain_text = "\n".join(dedupe_keep_order([item for item in cleaned if item]))
    segments = [
        TranscriptSegment(index=index, start=None, end=None, text=item)
        for index, item in enumerate([item for item in cleaned if item], start=1)
    ]
    return plain_text, segments


def _parse_timestamp(value: str) -> float:
    normalized = value.replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds = float(parts[1])
    else:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def _json3_ms_to_seconds(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None
