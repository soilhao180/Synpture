from __future__ import annotations

from src.models import TranscriptChunk, TranscriptSegment
from src.utils import has_timeline


def build_chunks(
    segments: list[TranscriptSegment],
    max_minutes: int,
    gap_seconds: int,
    max_chars: int = 2200,
) -> list[TranscriptChunk]:
    if not segments:
        return []

    if _segments_have_timeline(segments):
        return _build_timed_chunks(
            segments=segments,
            max_minutes=max_minutes,
            gap_seconds=gap_seconds,
            max_chars=max_chars,
        )
    return _build_text_chunks(segments=segments, max_chars=max_chars)


def _build_timed_chunks(
    *,
    segments: list[TranscriptSegment],
    max_minutes: int,
    gap_seconds: int,
    max_chars: int,
) -> list[TranscriptChunk]:
    chunks: list[TranscriptChunk] = []
    current_segments: list[TranscriptSegment] = []
    current_chars = 0
    max_duration = max_minutes * 60

    for segment in segments:
        if not current_segments:
            current_segments = [segment]
            current_chars = len(segment.text)
            continue

        first = current_segments[0]
        previous = current_segments[-1]
        duration = (segment.end or 0.0) - (first.start or 0.0)
        silence_gap = max(0.0, (segment.start or 0.0) - (previous.end or 0.0))
        projected_chars = current_chars + len(segment.text)

        should_split = (
            silence_gap >= gap_seconds
            or duration >= max_duration
            or projected_chars >= max_chars
        )

        if should_split:
            chunks.append(_create_chunk(len(chunks) + 1, current_segments))
            current_segments = [segment]
            current_chars = len(segment.text)
        else:
            current_segments.append(segment)
            current_chars = projected_chars

    if current_segments:
        chunks.append(_create_chunk(len(chunks) + 1, current_segments))

    return chunks


def _build_text_chunks(*, segments: list[TranscriptSegment], max_chars: int) -> list[TranscriptChunk]:
    chunks: list[TranscriptChunk] = []
    current_segments: list[TranscriptSegment] = []
    current_chars = 0

    for segment in segments:
        segment_text = segment.text.strip()
        if not segment_text:
            continue

        projected_chars = current_chars + len(segment_text)
        if current_segments and projected_chars >= max_chars:
            chunks.append(_create_chunk(len(chunks) + 1, current_segments))
            current_segments = [segment]
            current_chars = len(segment_text)
            continue

        current_segments.append(segment)
        current_chars = projected_chars

    if current_segments:
        chunks.append(_create_chunk(len(chunks) + 1, current_segments))

    return chunks


def _create_chunk(index: int, segments: list[TranscriptSegment]) -> TranscriptChunk:
    text = "\n\n".join(segment.text.strip() for segment in segments if segment.text.strip())
    first = segments[0]
    last = segments[-1]
    start = first.start if has_timeline(first.start, first.end) else None
    end = last.end if has_timeline(last.start, last.end) else None
    return TranscriptChunk(
        index=index,
        start=start,
        end=end,
        text=text.strip(),
        segments=list(segments),
    )


def _segments_have_timeline(segments: list[TranscriptSegment]) -> bool:
    return all(has_timeline(segment.start, segment.end) for segment in segments)
