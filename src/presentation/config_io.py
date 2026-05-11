from __future__ import annotations

import os
import re
from pathlib import Path


ENV_WRITEBACK_KEYS = (
    "SUMMARY_API_BASE_URL",
    "SUMMARY_API_KEY",
    "SUMMARY_API_MODEL",
    "TRANSCRIBE_BACKEND",
)

_ENV_ASSIGNMENT_RE = re.compile(r"^([^\S\r\n]*)([A-Za-z_][A-Za-z0-9_]*)([^\S\r\n]*=[^\S\r\n]*)([^\r\n]*)(\r?\n)?$")
_ORPHAN_SECRET_RE = re.compile(r'^\s*"?sk-[A-Za-z0-9_\-]{16,}"?\s*$')


def save_env_settings(env_path: str | Path, values: dict[str, str | None]) -> dict[str, str]:
    resolved_path = Path(env_path)
    normalized = _normalize_values(values)

    lines = resolved_path.read_text(encoding="utf-8").splitlines(keepends=True) if resolved_path.exists() else []
    output_lines: list[str] = []
    seen: set[str] = set()

    for line in lines:
        match = _ENV_ASSIGNMENT_RE.match(line)
        if not match:
            if _looks_like_orphan_secret(line):
                continue
            output_lines.append(line)
            continue

        key = match.group(2)
        if key not in normalized:
            output_lines.append(line)
            continue

        prefix = match.group(1)
        separator = match.group(3)
        newline = match.group(5) or "\n"
        output_lines.append(f"{prefix}{key}{separator}{_format_env_value(normalized[key])}{newline}")
        seen.add(key)

    if output_lines and not output_lines[-1].endswith(("\n", "\r")):
        output_lines[-1] = output_lines[-1] + "\n"

    for key in ENV_WRITEBACK_KEYS:
        if key not in normalized or key in seen:
            continue
        output_lines.append(f"{key}={_format_env_value(normalized[key])}\n")

    resolved_path.write_text("".join(output_lines), encoding="utf-8")
    for key, value in normalized.items():
        os.environ[key] = value
    return normalized


def _normalize_values(values: dict[str, str | None]) -> dict[str, str]:
    invalid_keys = set(values) - set(ENV_WRITEBACK_KEYS)
    if invalid_keys:
        invalid = ", ".join(sorted(invalid_keys))
        raise ValueError(f"Unsupported env keys: {invalid}")

    normalized: dict[str, str] = {}
    for key, value in values.items():
        normalized[key] = _normalize_value(key, value)
    return normalized


def _normalize_value(key: str, value: str | None) -> str:
    if value is None:
        return ""
    normalized = str(value).strip()
    if "\r" in normalized or "\n" in normalized:
        raise ValueError(f"{key} cannot contain line breaks.")
    return normalized


def _looks_like_orphan_secret(line: str) -> bool:
    stripped = line.strip()
    if not stripped or "=" in stripped or stripped.startswith("#"):
        return False
    return bool(_ORPHAN_SECRET_RE.match(stripped))


def _format_env_value(value: str) -> str:
    if value == "":
        return ""
    if value != value.strip() or any(char.isspace() for char in value) or "#" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
