from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_run_directory(output_root: Path, label: str) -> Path:
    safe_name = slugify_filename(Path(label).stem or label)
    run_dir = output_root / f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return ensure_directory(run_dir)


def slugify_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "_", name, flags=re.UNICODE).strip("._")
    return cleaned or "video"


def format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def has_timeline(start: float | None, end: float | None) -> bool:
    return start is not None and end is not None


def write_text(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def write_json(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def run_command(command: list[str], error_message: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            **hidden_subprocess_kwargs(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{error_message}: 未找到命令 {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(f"{error_message}: {details}") from exc


def hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("模型没有返回 JSON 内容。")

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise ValueError("无法从模型返回中提取 JSON。")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("JSON 返回不是对象。")
    return parsed


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = normalize_whitespace(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def file_size_mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024
