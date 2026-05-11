from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any, Callable

from src.config import Settings
from src.models import TranscriptResult, TranscriptSegment
from src.runtime_paths import get_windows_debug_crt_dependencies
from src.segmenter import build_chunks
from src.transcription_runtime import resolve_transcription_backend_choice
from src.transcribers.whisper_cpp import WhisperCppTranscriber
from src.utils import format_timestamp, hidden_subprocess_kwargs, run_command, timestamp_now


ProgressHook = Callable[[str, str, dict[str, Any] | None], None]
LOCAL_GPU_CHUNK_THRESHOLD_SECONDS = 12 * 60
LOCAL_GPU_CHUNK_SECONDS = 8 * 60


def transcribe_video(
    video_path: Path,
    output_dir: Path,
    settings: Settings,
    progress_hook: ProgressHook | None = None,
    ) -> TranscriptResult:
    _ensure_binary_available(settings.ffmpeg_bin, "ffmpeg")
    _ensure_binary_available(settings.whisper_cpp_bin, "whisper.cpp")
    _ensure_whisper_cpp_binary_portable(settings.whisper_cpp_bin)
    _ensure_model_available(settings.whisper_cpp_model_path)

    backend = settings.transcribe_backend
    if backend not in {"auto", "local"}:
        raise RuntimeError("当前版本只支持本地 GPU-only 转录。")

    _ensure_local_runtime_supported()
    selected_device = resolve_transcription_backend_choice(settings)
    return _transcribe_with_local(
        video_path,
        output_dir,
        settings,
        progress_hook=progress_hook,
        device=selected_device,
    )


def run_gpu_diagnostic(
    audio_path: Path,
    output_dir: Path,
    settings: Settings,
    progress_hook: ProgressHook | None = None,
) -> dict[str, Any]:
    total_duration = _get_wav_duration(audio_path)
    chunks = _split_audio_for_local_if_needed(
        audio_path=audio_path,
        output_dir=output_dir,
        settings=settings,
        total_duration=total_duration,
        device="gpu",
    )
    result = _run_local_workers_for_chunks(
        audio_chunks=chunks,
        settings=settings,
        total_duration=total_duration,
        progress_hook=progress_hook,
        device="gpu",
    )
    return {
        "chunk_count": len(chunks),
        "notes": result["notes"],
        "diagnostics": result["diagnostics"],
        "segment_count": len(result["segments"]),
        "language": result["language"],
    }


def _transcribe_with_local(
    video_path: Path,
    output_dir: Path,
    settings: Settings,
    progress_hook: ProgressHook | None = None,
    *,
    device: str = "gpu",
) -> TranscriptResult:
    audio_path = output_dir / "audio.wav"
    _notify(progress_hook, "extracting_audio", "使用 ffmpeg 提取本地转录音频。")
    _extract_audio_for_local(video_path, audio_path, settings)

    total_duration = _get_wav_duration(audio_path)
    _notify(progress_hook, "transcribing", "使用 whisper.cpp 执行本地 GPU 转录。")

    audio_chunks = _split_audio_for_local_if_needed(
        audio_path=audio_path,
        output_dir=output_dir,
        settings=settings,
        total_duration=total_duration,
        device="cuda",
    )
    notes: list[str] = []
    if len(audio_chunks) > 1:
        notes.append(f"长音频已切分为 {len(audio_chunks)} 段，按顺序使用 whisper.cpp GPU 转录。")

    worker_result = _run_local_workers_for_chunks(
        audio_chunks=audio_chunks,
        settings=settings,
        total_duration=total_duration,
        progress_hook=progress_hook,
        device=device,
    )
    notes.extend(worker_result["notes"])
    notes.append("当前使用 whisper.cpp GPU-only 本地转录。")

    segments = worker_result["segments"]
    language = worker_result["language"]
    transcript_text = "\n".join(segment.text for segment in segments)
    chunks = build_chunks(
        segments=segments,
        max_minutes=settings.chunk_max_minutes,
        gap_seconds=settings.chunk_gap_seconds,
    )
    return TranscriptResult(
        video_path=video_path,
        audio_path=audio_path,
        output_dir=output_dir,
        backend_used="local-gpu" if device == "gpu" else "local-cpu",
        model_used=settings.whisper_cpp_model_path.name,
        language=language,
        transcript_text=transcript_text,
        segments=segments,
        chunks=chunks,
        notes=notes,
        gpu_diagnostics=worker_result["diagnostics"],
    )


def _run_local_workers_for_chunks(
    *,
    audio_chunks: list[tuple[Path, float]],
    settings: Settings,
    total_duration: float,
    progress_hook: ProgressHook | None,
    device: str,
) -> dict[str, Any]:
    all_segments: list[TranscriptSegment] = []
    notes: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    language = settings.local_whisper_language
    device_label = "GPU" if device == "gpu" else "CPU"

    for chunk_index, (chunk_path, offset_seconds) in enumerate(audio_chunks, start=1):
        chunk_duration = _get_wav_duration(chunk_path)
        if len(audio_chunks) > 1:
            _notify(
                progress_hook,
                "transcribing",
                (
                    f"本地转录分片 {chunk_index}/{len(audio_chunks)}："
                    f"{format_timestamp(offset_seconds)} - {format_timestamp(offset_seconds + chunk_duration)}"
                ),
                extra={
                    "active_chunk_index": chunk_index,
                    "active_chunk_total": len(audio_chunks),
                },
            )

        diagnostics.append(
            _build_gpu_diagnostic_entry(
                event="chunk_start",
                chunk_index=chunk_index,
                chunk_total=len(audio_chunks),
                device=device,
                note=f"开始转录分片 {chunk_index}/{len(audio_chunks)}",
                gpu_snapshot=_capture_gpu_snapshot(),
            )
        )

        worker_result = _run_local_worker(
            audio_path=chunk_path,
            settings=settings,
            total_duration=total_duration,
            progress_hook=progress_hook,
            time_offset=offset_seconds,
            chunk_index=chunk_index,
            chunk_total=len(audio_chunks),
            device=device,
        )
        diagnostics.extend(worker_result["diagnostics"])

        if worker_result["return_code"] != 0:
            snapshot = _capture_gpu_snapshot()
            diagnostics.append(
                _build_gpu_diagnostic_entry(
                    event="chunk_failed",
                    chunk_index=chunk_index,
                    chunk_total=len(audio_chunks),
                    device=device,
                    worker_pid=worker_result.get("worker_pid"),
                    return_code=worker_result["return_code"],
                    gpu_snapshot=snapshot,
                    result_exists=worker_result["result_exists"],
                    segment_count=len(worker_result["segments"]),
                    note=worker_result["error_message"] or "GPU worker 失败",
                )
            )
            raise RuntimeError(
                "GPU-only 任务失败，"
                f"失败分片 {chunk_index}/{len(audio_chunks)}，"
                f"退出码 {worker_result['return_code']}，"
                f"最近显存 {snapshot.get('gpu_memory_used_mb', '-')} MB，"
                f"错误：{worker_result['error_message'] or '未知错误'}"
            )

        for item in worker_result["segments"]:
            all_segments.append(
                TranscriptSegment(
                    index=len(all_segments) + 1,
                    start=item.start + offset_seconds,
                    end=item.end + offset_seconds,
                    text=item.text,
                )
            )
        notes.extend(worker_result["notes"])
        language = str(worker_result["language"])

        diagnostics.append(
            _build_gpu_diagnostic_entry(
                event="chunk_completed",
                chunk_index=chunk_index,
                chunk_total=len(audio_chunks),
                device=device,
                worker_pid=worker_result.get("worker_pid"),
                return_code=worker_result["return_code"],
                gpu_snapshot=_capture_gpu_snapshot(),
                result_exists=worker_result["result_exists"],
                segment_count=len(worker_result["segments"]),
                note=f"分片 {chunk_index}/{len(audio_chunks)} 转录完成",
            )
        )
        if device == "gpu":
            cleanup_entry = _wait_for_gpu_cleanup(settings)
            cleanup_entry["chunk_index"] = chunk_index
            cleanup_entry["chunk_total"] = len(audio_chunks)
            diagnostics.append(cleanup_entry)

    return {
        "segments": all_segments,
        "language": language,
        "notes": notes,
        "diagnostics": diagnostics,
    }


def _resolve_whisper_cpp_binary(settings: Settings, device: str) -> str:
    if device == "cpu":
        cpu_candidate = Path(settings.whisper_cpp_cpu_bin)
        if cpu_candidate.exists():
            return str(cpu_candidate.resolve())
    return settings.whisper_cpp_bin


def _run_local_worker(
    *,
    audio_path: Path,
    settings: Settings,
    total_duration: float,
    progress_hook: ProgressHook | None,
    time_offset: float = 0.0,
    chunk_index: int = 1,
    chunk_total: int = 1,
    device: str = "gpu",
) -> dict[str, Any]:
    result_prefix = audio_path.parent / f"{audio_path.stem}_whispercpp"
    result_path = result_prefix.with_suffix(".json")
    stdout_log_path = audio_path.parent / f"{audio_path.stem}_whispercpp.stdout.log"
    stderr_log_path = audio_path.parent / f"{audio_path.stem}_whispercpp.stderr.log"
    result_path.unlink(missing_ok=True)
    stdout_log_path.unlink(missing_ok=True)
    stderr_log_path.unlink(missing_ok=True)

    transcriber = WhisperCppTranscriber(
        binary_path=_resolve_whisper_cpp_binary(settings, device),
        model_path=settings.whisper_cpp_model_path,
        language=settings.local_whisper_language,
        prompt=settings.local_whisper_prompt,
    )
    command = transcriber.build_command(
        audio_path=audio_path,
        output_prefix=result_prefix,
        disable_gpu=device == "cpu",
    )
    binary_dir = str(Path(transcriber.binary_path).resolve().parent)
    env = dict(os.environ)
    env["PATH"] = binary_dir + ";" + env.get("PATH", "")
    diagnostics: list[dict[str, Any]] = []
    last_heartbeat_at = timestamp_now()
    last_segment_at: str | None = None
    last_progress_state = {"last_end": time_offset}

    with stdout_log_path.open("w", encoding="utf-8") as stdout_handle, stderr_log_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=binary_dir,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )

        diagnostics.append(
            _build_gpu_diagnostic_entry(
                event="worker_spawned",
                chunk_index=chunk_index,
                chunk_total=chunk_total,
                device=device,
                worker_pid=process.pid,
                gpu_snapshot=_capture_gpu_snapshot(),
                note=f"whisper.cpp 已启动：PID {process.pid}",
            )
        )

        while process.poll() is None:
            time.sleep(max(0.5, float(settings.gpu_heartbeat_seconds)))
            last_heartbeat_at = timestamp_now()
            snapshot = _capture_gpu_snapshot()
            diagnostics.append(
                _build_gpu_diagnostic_entry(
                    event="heartbeat",
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                    device=device,
                    worker_pid=process.pid,
                    gpu_snapshot=snapshot,
                    note="whisper.cpp 仍在推理，暂未生成分片结果文件。",
                )
            )
            _notify(
                progress_hook,
                "transcribing",
                (
                    "本地转录仍在推理，尚未生成该分片结果。"
                    f" 当前分片 {chunk_index}/{chunk_total}"
                ),
                extra={
                    "worker_pid": process.pid,
                    "last_heartbeat_at": last_heartbeat_at,
                    "last_segment_at": last_segment_at,
                    "active_chunk_index": chunk_index,
                    "active_chunk_total": chunk_total,
                    "gpu_memory_used_mb": snapshot.get("gpu_memory_used_mb"),
                },
            )

        process.wait()

    file_payload = _wait_for_worker_result_file(result_path)
    stdout_text = stdout_log_path.read_text(encoding="utf-8", errors="replace") if stdout_log_path.exists() else ""
    stderr_text = stderr_log_path.read_text(encoding="utf-8", errors="replace") if stderr_log_path.exists() else ""
    if file_payload is not None and process.returncode == 0:
        segments, language, notes = transcriber.load_result(
            json_path=result_path,
            progress_callback=lambda current_end: _report_local_progress(
                progress_hook=progress_hook,
                current_end=current_end,
                total_duration=total_duration,
                progress_state=last_progress_state,
                time_offset=time_offset,
                extra={
                    "worker_pid": process.pid,
                    "last_heartbeat_at": last_heartbeat_at,
                    "last_segment_at": timestamp_now(),
                    "active_chunk_index": chunk_index,
                    "active_chunk_total": chunk_total,
                    "gpu_memory_used_mb": _capture_gpu_snapshot().get("gpu_memory_used_mb"),
                },
            ),
        )
        last_segment_at = timestamp_now()
        return {
            "segments": segments,
            "language": language,
            "notes": notes,
            "return_code": process.returncode,
            "worker_pid": process.pid,
            "result_exists": True,
            "error_message": None,
            "diagnostics": diagnostics,
        }

    error_message = stderr_text.strip() or stdout_text.strip() or "whisper.cpp 未生成结果文件。"
    return {
        "segments": [],
        "language": settings.local_whisper_language,
        "notes": [],
        "return_code": process.returncode if process.returncode is not None else 1,
        "worker_pid": process.pid,
        "result_exists": result_path.exists(),
        "error_message": error_message,
        "diagnostics": diagnostics,
    }


def _report_local_progress(
    *,
    progress_hook: ProgressHook | None,
    current_end: float,
    total_duration: float,
    progress_state: dict[str, float],
    time_offset: float,
    extra: dict[str, Any] | None = None,
) -> None:
    effective_end = current_end + time_offset
    last_reported_end = progress_state["last_end"]
    if effective_end <= last_reported_end:
        return
    if last_reported_end >= 0 and effective_end - last_reported_end < 20 and effective_end < total_duration:
        return
    progress_state["last_end"] = effective_end
    detail = f"本地转录进行中：已处理到 {format_timestamp(effective_end)}"
    if total_duration > 0:
        detail += f" / {format_timestamp(total_duration)}"
    _notify(progress_hook, "transcribing", detail, extra=extra)


def _ensure_binary_available(binary: str, display_name: str) -> None:
    if Path(binary).exists() or shutil.which(binary):
        return
    raise RuntimeError(f"未找到 {display_name}：{binary}")


def _ensure_model_available(model_path: Path) -> None:
    if model_path.exists():
        return
    raise RuntimeError(f"未找到 whisper.cpp 模型文件：{model_path}")


def _ensure_whisper_cpp_binary_portable(binary: str) -> None:
    debug_dependencies = get_windows_debug_crt_dependencies(binary)
    if not debug_dependencies:
        return
    dependency_text = ", ".join(debug_dependencies)
    raise RuntimeError(
        "Current whisper.cpp binary is not a distributable Release build. "
        f"Detected Debug CRT dependencies: {dependency_text}. "
        "Please replace it with a Release CUDA build before running transcription."
    )


def _ensure_local_runtime_supported(version_info: tuple[int, int, int] | None = None) -> None:
    major, minor, micro = version_info or sys.version_info[:3]
    if major == 3 and minor >= 11:
        return
    raise RuntimeError(
        f"当前 Python 版本为 {major}.{minor}.{micro}，请改用 Python 3.11 或更高版本。"
    )


def _extract_audio_for_local(video_path: Path, audio_path: Path, settings: Settings) -> None:
    run_command(
        [
            settings.ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(audio_path),
        ],
        "提取本地转录音频失败",
    )


def _split_audio_for_local_if_needed(
    *,
    audio_path: Path,
    output_dir: Path,
    settings: Settings,
    total_duration: float,
    device: str,
) -> list[tuple[Path, float]]:
    if not _should_chunk_local_audio(total_duration=total_duration, device=device):
        return [(audio_path, 0.0)]

    chunks: list[tuple[Path, float]] = []
    current_start = 0.0
    chunk_index = 1

    while current_start < total_duration:
        current_length = min(LOCAL_GPU_CHUNK_SECONDS, total_duration - current_start)
        chunk_path = output_dir / f"audio_local_chunk_{chunk_index:02d}.wav"
        run_command(
            [
                settings.ffmpeg_bin,
                "-y",
                "-ss",
                str(current_start),
                "-t",
                str(current_length),
                "-i",
                str(audio_path),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(chunk_path),
            ],
            "切分本地转录音频失败",
        )
        chunks.append((chunk_path, current_start))
        current_start += current_length
        chunk_index += 1

    return chunks


def _should_chunk_local_audio(*, total_duration: float, device: str) -> bool:
    return total_duration > LOCAL_GPU_CHUNK_THRESHOLD_SECONDS


def _get_wav_duration(audio_path: Path) -> float:
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if rate <= 0:
                return 0.0
            return frames / float(rate)
    except Exception:
        return 0.0


def _notify(
    progress_hook: ProgressHook | None,
    stage_key: str,
    detail: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if progress_hook:
        progress_hook(stage_key, detail, extra or {})


def _load_worker_result_file(result_path: Path) -> dict[str, object] | None:
    if not result_path.exists():
        return None
    raw = result_path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "gbk", "cp936"):
        try:
            payload = json.loads(raw.decode(encoding))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _wait_for_worker_result_file(
    result_path: Path,
    timeout_seconds: float = 2.0,
    poll_interval_seconds: float = 0.1,
) -> dict[str, object] | None:
    deadline = time.time() + timeout_seconds
    while time.time() <= deadline:
        payload = _load_worker_result_file(result_path)
        if payload is not None:
            return payload
        time.sleep(poll_interval_seconds)
    return _load_worker_result_file(result_path)


def _capture_gpu_snapshot() -> dict[str, Any]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {"gpu_memory_used_mb": None, "gpu_utilization_percent": None}
    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            **hidden_subprocess_kwargs(),
        )
        first_line = result.stdout.strip().splitlines()[0]
        memory_used, gpu_utilization = [part.strip() for part in first_line.split(",", 1)]
        return {
            "gpu_memory_used_mb": int(memory_used),
            "gpu_utilization_percent": int(gpu_utilization),
        }
    except Exception:
        return {"gpu_memory_used_mb": None, "gpu_utilization_percent": None}


def _wait_for_gpu_cleanup(settings: Settings) -> dict[str, Any]:
    deadline = time.time() + settings.gpu_cleanup_wait_seconds
    last_snapshot = _capture_gpu_snapshot()
    while time.time() <= deadline:
        snapshot = _capture_gpu_snapshot()
        last_snapshot = snapshot
        memory_used = snapshot.get("gpu_memory_used_mb")
        if memory_used is None or memory_used <= settings.gpu_idle_vram_threshold_mb:
            return _build_gpu_diagnostic_entry(
                event="gpu_cleanup_observed",
                chunk_index=None,
                chunk_total=None,
                device="cuda",
                gpu_snapshot=snapshot,
                note="检测到 GPU 显存已回落到阈值以内。",
            )
        time.sleep(1)
    return _build_gpu_diagnostic_entry(
        event="gpu_cleanup_timeout",
        chunk_index=None,
        chunk_total=None,
        device="cuda",
        gpu_snapshot=last_snapshot,
        note="等待 GPU 显存回落超时，继续执行下一分片。",
    )


def _build_gpu_diagnostic_entry(
    *,
    event: str,
    chunk_index: int | None,
    chunk_total: int | None,
    device: str,
    worker_pid: int | None = None,
    return_code: int | None = None,
    gpu_snapshot: dict[str, Any] | None = None,
    result_exists: bool | None = None,
    segment_count: int | None = None,
    note: str = "",
) -> dict[str, Any]:
    snapshot = gpu_snapshot or {}
    return {
        "timestamp": timestamp_now(),
        "event": event,
        "chunk_index": chunk_index,
        "chunk_total": chunk_total,
        "device": device,
        "worker_pid": worker_pid,
        "return_code": return_code,
        "gpu_memory_used_mb": snapshot.get("gpu_memory_used_mb"),
        "gpu_utilization_percent": snapshot.get("gpu_utilization_percent"),
        "result_exists": result_exists,
        "segment_count": segment_count,
        "note": note,
    }
