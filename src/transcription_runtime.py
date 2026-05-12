from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from src.config import Settings
from src.runtime_paths import get_runtime_state_path, get_windows_debug_crt_dependencies
from src.runtime_resources import effective_runtime_resource_paths
from src.utils import ensure_directory, hidden_subprocess_kwargs, timestamp_now


BackendChoice = Literal["gpu", "cpu"]
GpuStatus = Literal["ready", "recoverable", "unsupported", "unavailable"]


@dataclass
class TranscriptionRuntimeState:
    allow_cpu_fallback: bool = False


@dataclass
class TranscriptionCapability:
    gpu_status: GpuStatus
    gpu_reason: str
    gpu_recoverable: bool
    cpu_fallback_available: bool
    preferred_backend: BackendChoice
    allow_cpu_fallback: bool
    decision_required: bool
    nvidia_detected: bool
    cpu_reason: str
    gpu_details: list[str]


def load_transcription_runtime_state() -> TranscriptionRuntimeState:
    path = get_runtime_state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return TranscriptionRuntimeState()
    return TranscriptionRuntimeState(
        allow_cpu_fallback=bool(payload.get("allow_cpu_fallback")),
    )


def save_transcription_runtime_state(*, allow_cpu_fallback: bool) -> TranscriptionRuntimeState:
    path = get_runtime_state_path()
    ensure_directory(path.parent)
    payload = {
        "allow_cpu_fallback": bool(allow_cpu_fallback),
        "updated_at": timestamp_now(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return TranscriptionRuntimeState(allow_cpu_fallback=bool(allow_cpu_fallback))


def probe_transcription_capability(settings: Settings) -> TranscriptionCapability:
    state = load_transcription_runtime_state()
    resource_paths = effective_runtime_resource_paths()
    gpu_binary = _resolve_binary_path(resource_paths.get("whisper_gpu")) or _resolve_binary_path(settings.whisper_cpp_bin)
    cpu_binary = _resolve_binary_path(resource_paths.get("whisper_cpu")) or _resolve_binary_path(settings.whisper_cpp_cpu_bin) or gpu_binary
    model_path = resource_paths.get("model") or settings.whisper_cpp_model_path
    model_ready = model_path.exists()
    ffmpeg_binary = _resolve_binary_path(resource_paths.get("ffmpeg")) or _resolve_binary_path(settings.ffmpeg_bin)
    ffmpeg_ready = bool(ffmpeg_binary)

    nvidia_detected, nvidia_names = _detect_nvidia_hardware()
    gpu_details: list[str] = []
    if nvidia_names:
        gpu_details.extend([f"检测到显卡：{name}" for name in nvidia_names])

    gpu_status: GpuStatus = "ready"
    gpu_reason = "NVIDIA GPU 与 whisper.cpp GPU 运行环境可用。"
    gpu_recoverable = False

    if gpu_binary is None:
        gpu_status = "recoverable" if nvidia_detected else "unsupported"
        gpu_reason = "未找到 whisper.cpp GPU 版可执行文件。"
    else:
        debug_deps = get_windows_debug_crt_dependencies(gpu_binary)
        if debug_deps:
            gpu_status = "recoverable" if nvidia_detected else "unsupported"
            gpu_reason = f"GPU 版 whisper.cpp 引用了 Debug CRT：{', '.join(debug_deps)}。"
        else:
            gpu_ok, gpu_binary_reason = _probe_whisper_binary(gpu_binary)
            if not gpu_ok:
                gpu_status = "recoverable" if nvidia_detected else "unsupported"
                gpu_reason = gpu_binary_reason
            else:
                gpu_details.append(f"GPU 版 whisper.cpp：{gpu_binary}")

    if not model_ready:
        gpu_status = "recoverable" if nvidia_detected else "unavailable"
        gpu_reason = f"未找到 whisper.cpp 模型文件：{model_path}"
    if not ffmpeg_ready:
        gpu_status = "recoverable" if nvidia_detected else "unavailable"
        gpu_reason = "未找到 ffmpeg，可执行本地转录前缺少音频提取能力。"

    nvidia_smi_ready, nvidia_smi_reason = _probe_nvidia_runtime(nvidia_detected)
    if gpu_status == "ready" and not nvidia_smi_ready:
        gpu_status = "recoverable" if nvidia_detected else "unsupported"
        gpu_reason = nvidia_smi_reason

    if not nvidia_detected:
        gpu_status = "unsupported"
        gpu_reason = "未检测到 NVIDIA 显卡，当前机器不能使用 GPU 转录。"
    elif gpu_status != "ready":
        gpu_recoverable = True
        gpu_reason = f"已检测到 NVIDIA 显卡，但 GPU 运行环境不完整：{gpu_reason}"

    cpu_available, cpu_reason = _probe_cpu_fallback(
        cpu_binary=cpu_binary,
        model_ready=model_ready,
        ffmpeg_ready=ffmpeg_ready,
    )
    preferred_backend: BackendChoice = "gpu"
    decision_required = False
    if gpu_status == "ready":
        preferred_backend = "gpu"
    elif cpu_available and state.allow_cpu_fallback:
        preferred_backend = "cpu"
    elif cpu_available:
        preferred_backend = "gpu"
        decision_required = True
    else:
        preferred_backend = "gpu"

    return TranscriptionCapability(
        gpu_status=gpu_status,
        gpu_reason=gpu_reason,
        gpu_recoverable=gpu_recoverable,
        cpu_fallback_available=cpu_available,
        preferred_backend=preferred_backend,
        allow_cpu_fallback=state.allow_cpu_fallback,
        decision_required=decision_required,
        nvidia_detected=nvidia_detected,
        cpu_reason=cpu_reason,
        gpu_details=gpu_details,
    )


def resolve_transcription_backend_choice(settings: Settings) -> BackendChoice:
    capability = probe_transcription_capability(settings)
    if capability.gpu_status == "ready":
        return "gpu"
    if capability.cpu_fallback_available and capability.allow_cpu_fallback:
        return "cpu"
    raise RuntimeError(capability.gpu_reason)


def serialize_transcription_capability(capability: TranscriptionCapability) -> dict[str, Any]:
    payload = asdict(capability)
    payload["gpuStatus"] = payload.pop("gpu_status")
    payload["gpuReason"] = payload.pop("gpu_reason")
    payload["gpuRecoverable"] = payload.pop("gpu_recoverable")
    payload["cpuFallbackAvailable"] = payload.pop("cpu_fallback_available")
    payload["preferredBackend"] = payload.pop("preferred_backend")
    payload["allowCpuFallback"] = payload.pop("allow_cpu_fallback")
    payload["decisionRequired"] = payload.pop("decision_required")
    payload["nvidiaDetected"] = payload.pop("nvidia_detected")
    payload["cpuReason"] = payload.pop("cpu_reason")
    payload["gpuDetails"] = payload.pop("gpu_details")
    return payload


def _resolve_binary_path(binary: str) -> str | None:
    candidate = Path(binary)
    if candidate.exists():
        return str(candidate.resolve())
    resolved = shutil.which(binary)
    return str(Path(resolved).resolve()) if resolved else None


def _probe_whisper_binary(binary: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [binary, "-h"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            **hidden_subprocess_kwargs(),
        )
    except FileNotFoundError:
        return False, f"未找到 whisper.cpp 可执行文件：{binary}"
    except Exception as exc:
        return False, f"whisper.cpp 无法启动：{exc}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if detail:
            return False, f"whisper.cpp 无法正常启动：{detail}"
        return False, "whisper.cpp 无法正常启动。"
    return True, f"whisper.cpp 可用：{binary}"


def _detect_nvidia_hardware() -> tuple[bool, list[str]]:
    if os.name != "nt":
        return False, []
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            **hidden_subprocess_kwargs(),
        )
    except Exception:
        return False, []

    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return any("nvidia" in name.lower() for name in names), names


def _probe_nvidia_runtime(nvidia_detected: bool) -> tuple[bool, str]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        if nvidia_detected:
            return False, "检测到 NVIDIA 显卡，但未找到 nvidia-smi，驱动或 CUDA 运行环境未就绪。"
        return False, "未检测到 nvidia-smi。"

    try:
        result = subprocess.run(
            [executable, "--query-gpu=name,driver_version", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            **hidden_subprocess_kwargs(),
        )
    except Exception as exc:
        return False, f"nvidia-smi 调用失败：{exc}"

    first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not first_line:
        return False, "nvidia-smi 没有返回可用的 GPU 信息。"
    return True, first_line


def _probe_cpu_fallback(*, cpu_binary: str | None, model_ready: bool, ffmpeg_ready: bool) -> tuple[bool, str]:
    if cpu_binary is None:
        return False, "未找到 whisper.cpp CPU 兼容可执行文件。"
    debug_deps = get_windows_debug_crt_dependencies(cpu_binary)
    if debug_deps:
        return False, f"CPU 版 whisper.cpp 引用了 Debug CRT：{', '.join(debug_deps)}。"
    cpu_ok, cpu_binary_reason = _probe_whisper_binary(cpu_binary)
    if not cpu_ok:
        return False, cpu_binary_reason
    if not model_ready:
        return False, "未找到 whisper.cpp 模型文件，CPU 兼容模式也无法启动。"
    if not ffmpeg_ready:
        return False, "未找到 ffmpeg，CPU 兼容模式缺少音频提取能力。"
    return True, f"CPU 兼容模式可用：{cpu_binary}"
