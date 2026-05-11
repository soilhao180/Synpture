from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.runtime_paths import bundled_path, ensure_runtime_env, get_app_root, get_default_output_dir, get_env_path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency fallback
    def load_dotenv(*args, **kwargs) -> bool:
        return False


PROJECT_ROOT = get_app_root()
DEFAULT_OUTPUT_DIR = get_default_output_dir()


@dataclass
class Settings:
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    output_dir: Path = DEFAULT_OUTPUT_DIR
    transcribe_backend: str = "auto"
    whisper_cpp_bin: str = "whisper-cli"
    whisper_cpp_cpu_bin: str = str(bundled_path("third_party", "whisper.cpp", "build-core", "bin", "whisper-cli.exe"))
    whisper_cpp_model_path: Path = bundled_path("models", "ggml-large-v3-turbo-q5_0.bin")
    local_whisper_device: str = "auto"
    local_whisper_language: str = "zh"
    local_whisper_prompt: str = ""
    local_gpu_only: bool = True
    gpu_idle_vram_threshold_mb: int = 512
    gpu_cleanup_wait_seconds: int = 20
    gpu_heartbeat_seconds: int = 10
    summary_api_base_url: str | None = None
    summary_api_key: str | None = None
    summary_api_model: str = "gpt-5.4"
    chunk_max_minutes: int = 3
    chunk_gap_seconds: int = 12


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def load_settings(env_path: str | Path | None = None) -> Settings:
    resolved_env_path = Path(env_path) if env_path else get_env_path()
    if env_path is None:
        resolved_env_path = ensure_runtime_env(resolved_env_path)
    _clear_managed_env_keys()
    load_dotenv(resolved_env_path, override=False)
    _load_env_fallback(resolved_env_path)

    output_dir = Path(os.getenv("OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    whisper_cpp_model_path = Path(
        os.getenv("WHISPER_CPP_MODEL_PATH", str(bundled_path("models", "ggml-large-v3-turbo-q5_0.bin")))
    )
    if not whisper_cpp_model_path.is_absolute():
        whisper_cpp_model_path = PROJECT_ROOT / whisper_cpp_model_path

    return Settings(
        ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
        ffprobe_bin=os.getenv("FFPROBE_BIN", "ffprobe"),
        output_dir=output_dir,
        transcribe_backend=os.getenv("TRANSCRIBE_BACKEND", "auto").strip().lower(),
        whisper_cpp_bin=os.getenv("WHISPER_CPP_BIN", "whisper-cli"),
        whisper_cpp_cpu_bin=os.getenv(
            "WHISPER_CPP_CPU_BIN",
            str(bundled_path("third_party", "whisper.cpp", "build-core", "bin", "whisper-cli.exe")),
        ),
        whisper_cpp_model_path=whisper_cpp_model_path,
        local_whisper_device=os.getenv("LOCAL_WHISPER_DEVICE", "auto").strip().lower(),
        local_whisper_language=os.getenv("LOCAL_WHISPER_LANGUAGE", "zh"),
        local_whisper_prompt=os.getenv("LOCAL_WHISPER_PROMPT", ""),
        local_gpu_only=os.getenv("LOCAL_GPU_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"},
        gpu_idle_vram_threshold_mb=int(os.getenv("GPU_IDLE_VRAM_THRESHOLD_MB", "512")),
        gpu_cleanup_wait_seconds=int(os.getenv("GPU_CLEANUP_WAIT_SECONDS", "20")),
        gpu_heartbeat_seconds=int(os.getenv("GPU_HEARTBEAT_SECONDS", "10")),
        summary_api_base_url=_clean_optional(os.getenv("SUMMARY_API_BASE_URL")),
        summary_api_key=_clean_optional(os.getenv("SUMMARY_API_KEY")),
        summary_api_model=os.getenv("SUMMARY_API_MODEL", "gpt-5.4"),
        chunk_max_minutes=int(os.getenv("CHUNK_MAX_MINUTES", "3")),
        chunk_gap_seconds=int(os.getenv("CHUNK_GAP_SECONDS", "12")),
    )


def _load_env_fallback(env_path: Path) -> None:
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _clear_managed_env_keys() -> None:
    for key in (
        "FFMPEG_BIN",
        "FFPROBE_BIN",
        "TRANSCRIBE_BACKEND",
        "WHISPER_CPP_BIN",
        "WHISPER_CPP_CPU_BIN",
        "WHISPER_CPP_MODEL_PATH",
        "LOCAL_WHISPER_DEVICE",
        "LOCAL_WHISPER_LANGUAGE",
        "LOCAL_WHISPER_PROMPT",
        "LOCAL_GPU_ONLY",
        "GPU_IDLE_VRAM_THRESHOLD_MB",
        "GPU_CLEANUP_WAIT_SECONDS",
        "GPU_HEARTBEAT_SECONDS",
        "SUMMARY_API_BASE_URL",
        "SUMMARY_API_KEY",
        "SUMMARY_API_MODEL",
        "CHUNK_MAX_MINUTES",
        "CHUNK_GAP_SECONDS",
    ):
        os.environ.pop(key, None)
