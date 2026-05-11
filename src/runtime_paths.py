from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Synpture"
WINDOWS_DEBUG_CRT_DLLS = (
    "MSVCP140D.dll",
    "VCRUNTIME140D.dll",
    "VCRUNTIME140_1D.dll",
    "ucrtbased.dll",
)
_PACKAGED_RUNTIME_KEYS = {
    "OUTPUT_DIR",
    "WHISPER_CPP_BIN",
    "WHISPER_CPP_CPU_BIN",
    "WHISPER_CPP_MODEL_PATH",
    "FFMPEG_BIN",
    "FFPROBE_BIN",
    "SHARE_LINK_NODE_BIN",
    "SHARE_LINK_NODE_PATH",
}


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_app_root() -> Path:
    override = os.getenv("SYNPTURE_APP_ROOT")
    if override:
        return Path(override).resolve()
    if is_packaged():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_bundle_root() -> Path:
    override = os.getenv("SYNPTURE_BUNDLE_ROOT")
    if override:
        return Path(override).resolve()
    if is_packaged():
        return Path(getattr(sys, "_MEIPASS", get_app_root())).resolve()
    return get_app_root()


def get_user_data_root() -> Path:
    override = os.getenv("SYNPTURE_DATA_DIR")
    if override:
        return Path(override).resolve()
    if is_packaged():
        appdata = os.getenv("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return (base / APP_NAME).resolve()
    return get_app_root()


def get_env_path() -> Path:
    override = os.getenv("SYNPTURE_ENV_PATH")
    if override:
        return Path(override).resolve()
    return get_user_data_root() / ".env" if is_packaged() else get_app_root() / ".env"


def get_runtime_state_path() -> Path:
    override = os.getenv("SYNPTURE_RUNTIME_STATE_PATH")
    if override:
        return Path(override).resolve()
    return get_user_data_root() / "runtime-state.json" if is_packaged() else get_app_root() / ".runtime-state.json"


def get_default_output_dir() -> Path:
    return get_user_data_root() / "output" if is_packaged() else get_app_root() / "output"


def get_managed_auth_root() -> Path:
    return get_user_data_root() / "managed_auth_profiles" if is_packaged() else get_app_root() / "output" / "managed_auth_profiles"


def runtime_resource_path(*parts: str) -> Path:
    user_candidate = get_user_data_root().joinpath(*parts)
    bundle_candidate = bundled_path(*parts)
    if user_candidate.exists():
        return user_candidate
    if bundle_candidate.exists():
        return bundle_candidate
    return user_candidate if is_packaged() else bundle_candidate


def bundled_path(*parts: str) -> Path:
    bundle_candidate = get_bundle_root().joinpath(*parts)
    app_candidate = get_app_root().joinpath(*parts)
    if bundle_candidate.exists():
        return bundle_candidate
    if app_candidate.exists():
        return app_candidate
    return bundle_candidate


def user_data_path(*parts: str) -> Path:
    return get_user_data_root().joinpath(*parts)


def ensure_runtime_env(env_path: Path | None = None) -> Path:
    resolved = (env_path or get_env_path()).resolve()
    if resolved.exists():
        if is_packaged():
            current_text = resolved.read_text(encoding="utf-8")
            merged_text = _merge_packaged_runtime_defaults(current_text, replace_existing=False)
            if merged_text != current_text:
                resolved.write_text(merged_text, encoding="utf-8")
        return resolved

    resolved.parent.mkdir(parents=True, exist_ok=True)
    example = bundled_path(".env.example")
    if example.exists():
        text = example.read_text(encoding="utf-8")
    else:
        text = "OUTPUT_DIR=output\n"

    if is_packaged():
        text = _merge_packaged_runtime_defaults(text, replace_existing=True)

    resolved.write_text(text, encoding="utf-8")
    return resolved


def _merge_packaged_runtime_defaults(text: str, *, replace_existing: bool) -> str:
    defaults = {
        "OUTPUT_DIR": str(get_default_output_dir()),
        "WHISPER_CPP_BIN": str(runtime_resource_path("third_party", "transcription_runtime", "whisper.cpp", "build-cuda", "bin", "whisper-cli.exe")),
        "WHISPER_CPP_CPU_BIN": str(runtime_resource_path("third_party", "transcription_runtime", "whisper.cpp", "build-core", "bin", "whisper-cli.exe")),
        "WHISPER_CPP_MODEL_PATH": str(runtime_resource_path("models", "ggml-large-v3-turbo-q5_0.bin")),
        "FFMPEG_BIN": str(runtime_resource_path("third_party", "transcription_runtime", "ffmpeg", "bin", "ffmpeg.exe")),
        "FFPROBE_BIN": str(runtime_resource_path("third_party", "transcription_runtime", "ffmpeg", "bin", "ffprobe.exe")),
        "SHARE_LINK_NODE_BIN": str(runtime_resource_path("third_party", "browser_runtime", "node", "node.exe")),
        "SHARE_LINK_NODE_PATH": str(runtime_resource_path("third_party", "browser_runtime", "node_runtime", "node_modules")),
    }
    merged = text
    for key, value in defaults.items():
        if replace_existing:
            merged = _replace_env_value(merged, key, value)
            continue
        merged = _upsert_env_value(
            merged,
            key,
            value,
            replace_blank=True,
            replace_invalid=is_packaged(),
        )
    return merged


def _replace_env_value(text: str, key: str, value: str) -> str:
    lines = text.splitlines(keepends=True)
    replacement = f"{key}={value}\n"
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        current_key, _ = stripped.split("=", 1)
        if current_key.strip() == key:
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            lines[index] = f"{key}={value}{newline}"
            return "".join(lines)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] = lines[-1] + "\n"
    lines.append(replacement)
    return "".join(lines)


def _upsert_env_value(text: str, key: str, value: str, *, replace_blank: bool, replace_invalid: bool) -> str:
    lines = text.splitlines(keepends=True)
    replacement = f"{key}={value}\n"
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        current_key, current_value = stripped.split("=", 1)
        if current_key.strip() == key:
            normalized_value = current_value.strip()
            if replace_blank and normalized_value:
                if not (replace_invalid and _should_replace_packaged_value(key, normalized_value)):
                    return "".join(lines)
            elif not replace_blank and not replace_invalid:
                return "".join(lines)
            elif replace_invalid and not _should_replace_packaged_value(key, normalized_value):
                return "".join(lines)
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            lines[index] = f"{key}={value}{newline}"
            return "".join(lines)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] = lines[-1] + "\n"
    lines.append(replacement)
    return "".join(lines)


def _should_replace_packaged_value(key: str, current_value: str) -> bool:
    if key not in _PACKAGED_RUNTIME_KEYS:
        return False

    stripped = current_value.strip()
    if not stripped:
        return True

    if key == "OUTPUT_DIR":
        return False

    candidate = Path(stripped)
    if not candidate.is_absolute():
        return True

    return not candidate.exists()


def get_windows_debug_crt_dependencies(binary_path: str | Path) -> tuple[str, ...]:
    path = Path(binary_path)
    if not path.exists() or path.suffix.lower() not in {".exe", ".dll"}:
        return ()

    try:
        raw = path.read_bytes().lower()
    except OSError:
        return ()

    matches = [name for name in WINDOWS_DEBUG_CRT_DLLS if name.lower().encode("ascii") in raw]
    return tuple(matches)
