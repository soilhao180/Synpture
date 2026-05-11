from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from src.models import TranscriptSegment

JSON_FALLBACK_ENCODINGS = ("utf-8", "utf-8-sig", "latin-1", "gbk", "cp936")


class WhisperCppTranscriber:
    def __init__(
        self,
        *,
        binary_path: str,
        model_path: Path,
        language: str,
        prompt: str,
    ) -> None:
        self.binary_path = binary_path
        self.model_path = model_path
        self.language = language
        self.prompt = prompt.strip()

    def build_command(
        self,
        *,
        audio_path: Path,
        output_prefix: Path,
        disable_gpu: bool = False,
    ) -> list[str]:
        resolved_audio_path = audio_path.resolve()
        resolved_output_prefix = output_prefix.resolve()
        resolved_model_path = self.model_path.resolve()
        command = [
            self.binary_path,
            "-m",
            str(resolved_model_path),
            "-f",
            str(resolved_audio_path),
            "-l",
            self.language,
            "-ojf",
            "-of",
            str(resolved_output_prefix),
        ]
        if self.prompt:
            command.extend(["--prompt", self.prompt])
        if disable_gpu:
            command.append("--no-gpu")
        return command

    def load_result(
        self,
        *,
        json_path: Path,
        progress_callback: Callable[[float], None] | None = None,
    ) -> tuple[list[TranscriptSegment], str, list[str]]:
        if not json_path.exists():
            raise RuntimeError(f"whisper.cpp 未生成结果文件：{json_path}")

        payload = _load_json_with_fallback(json_path)

        result_meta = payload.get("result", {})
        language = str(payload.get("language") or result_meta.get("language") or self.language)
        notes: list[str] = []
        parsed_segments: list[TranscriptSegment] = []

        raw_segments = payload.get("transcription") or payload.get("segments") or []
        if not isinstance(raw_segments, list):
            raise RuntimeError("whisper.cpp 返回格式不兼容：缺少 transcription 列表。")

        for index, item in enumerate(raw_segments, start=1):
            if not isinstance(item, dict):
                continue
            text = _repair_whisper_cpp_text(item.get("text", "")).strip()
            if not text:
                continue
            offsets = item.get("offsets", {})
            if offsets:
                start = _coerce_millisecond_offset(offsets.get("from"))
                end = _coerce_millisecond_offset(offsets.get("to"))
            elif "start" in item or "end" in item:
                start = _coerce_time(item.get("start"))
                end = _coerce_time(item.get("end"))
            else:
                start = _coerce_token_time(item.get("t0"))
                end = _coerce_token_time(item.get("t1"))
            if end < start:
                end = start
            if progress_callback is not None:
                progress_callback(end)
            parsed_segments.append(
                TranscriptSegment(
                    index=index,
                    start=start,
                    end=end,
                    text=text,
                )
            )

        return parsed_segments, language, notes


def _coerce_time(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        text = str(value).strip()
        if not text:
            return 0.0
        try:
            numeric = float(text)
        except ValueError:
            return 0.0
    if numeric > 1000:
        return numeric / 1000.0
    return numeric


def _coerce_millisecond_offset(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def _coerce_token_time(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _load_json_with_fallback(path: Path) -> dict:
    raw = path.read_bytes()
    last_error: Exception | None = None
    for encoding in JSON_FALLBACK_ENCODINGS:
        try:
            payload = json.loads(raw.decode(encoding))
        except Exception as exc:
            last_error = exc
            continue
        if isinstance(payload, dict):
            return payload
        raise RuntimeError("whisper.cpp 结果 JSON 不是对象。")
    raise RuntimeError(f"whisper.cpp 结果 JSON 解析失败：{last_error}")


def _repair_whisper_cpp_text(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return text
