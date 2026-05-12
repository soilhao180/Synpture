from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import src.runtime_paths as runtime_paths
from src.runtime_paths import bundled_path, get_app_root, get_user_data_root, is_packaged, user_data_path


MANIFEST_PATH = bundled_path("packaging", "runtime_resources.json")
_DOWNLOAD_LOCK = threading.Lock()
_DOWNLOADS: dict[str, dict[str, Any]] = {}

_DEV_SOURCE_LAYOUTS: dict[str, tuple[Path, tuple[str, ...]]] = {
    "model": (
        Path("models") / "ggml-large-v3-turbo-q5_0.bin",
        (),
    ),
    "browser_runtime": (
        Path("third_party"),
        (
            "node/node.exe",
            "node_runtime/node_modules/playwright/package.json",
            "chromium/chrome.exe",
        ),
    ),
    "transcription_runtime": (
        Path("third_party"),
        (
            "ffmpeg/bin/ffmpeg.exe",
            "ffmpeg/bin/ffprobe.exe",
            "whisper.cpp/build-cuda/bin/whisper-cli.exe",
            "whisper.cpp/build-core/bin/whisper-cli.exe",
        ),
    ),
}


@dataclass(frozen=True)
class RuntimeResource:
    id: str
    title: str
    description: str
    url: str
    sha256: str
    archive: bool
    target: str
    markers: tuple[str, ...]
    required_for: tuple[str, ...]

    @property
    def target_path(self) -> Path:
        return user_data_path(*Path(self.target).parts)

    @property
    def ready_paths(self) -> tuple[Path, ...]:
        if self.markers:
            return tuple(self.target_path / marker for marker in self.markers)
        return (self.target_path,)


def load_runtime_resources() -> list[RuntimeResource]:
    if not MANIFEST_PATH.exists():
        return []
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    resources = []
    for item in payload.get("resources", []):
        resources.append(
            RuntimeResource(
                id=str(item.get("id") or "").strip(),
                title=str(item.get("title") or "").strip(),
                description=str(item.get("description") or "").strip(),
                url=str(item.get("url") or "").strip(),
                sha256=str(item.get("sha256") or "").strip().lower(),
                archive=bool(item.get("archive")),
                target=str(item.get("target") or "").strip(),
                markers=tuple(str(marker).strip() for marker in item.get("markers", []) if str(marker).strip()),
                required_for=tuple(str(value).strip() for value in item.get("requiredFor", []) if str(value).strip()),
            )
        )
    return [resource for resource in resources if resource.id and resource.target]


def get_runtime_resource(resource_id: str) -> RuntimeResource:
    for resource in load_runtime_resources():
        if resource.id == resource_id:
            return resource
    raise KeyError(resource_id)


def serialize_runtime_resources() -> list[dict[str, Any]]:
    return [serialize_runtime_resource(resource) for resource in load_runtime_resources()]


def serialize_runtime_resource(resource: RuntimeResource) -> dict[str, Any]:
    status = get_runtime_resource_status(resource.id)
    target_path = status.pop("targetPath", resource.target_path)
    return {
        "id": resource.id,
        "title": resource.title,
        "description": resource.description,
        "requiredFor": list(resource.required_for),
        "targetPath": str(target_path),
        "fileName": _resource_file_name(resource),
        "urlConfigured": bool(resource.url),
        "sha256Configured": bool(resource.sha256),
        **status,
    }


def get_runtime_resource_status(resource_id: str) -> dict[str, Any]:
    resource = get_runtime_resource(resource_id)
    with _DOWNLOAD_LOCK:
        download = dict(_DOWNLOADS.get(resource_id, {}))

    target_path = _effective_target_path(resource)
    ready_paths = _effective_ready_paths(resource)
    ready = all(path.exists() for path in ready_paths)
    missing = [str(path) for path in ready_paths if not path.exists()]
    state = "ready" if ready else "missing"
    detail = "资源已安装。" if ready else "资源未安装。"

    if download:
        state = str(download.get("state") or state)
        detail = str(download.get("detail") or detail)

    if ready and resource.sha256 and not resource.archive and target_path == resource.target_path:
        actual = _sha256_file(resource.target_path)
        if actual != resource.sha256:
            state = "invalid"
            detail = "资源校验失败，请重新下载。"

    return {
        "state": state,
        "ready": ready and state != "invalid",
        "detail": detail,
        "targetPath": str(target_path),
        "missing": missing,
        "progressPercent": int(download.get("progressPercent", 100 if ready else 0)),
        "error": download.get("error"),
        "updatedAt": download.get("updatedAt"),
    }


def start_runtime_resource_download(resource_id: str) -> dict[str, Any]:
    resource = get_runtime_resource(resource_id)
    if not resource.url:
        raise RuntimeError(f"{resource.title} 未配置下载地址。")
    if not resource.sha256:
        raise RuntimeError(f"{resource.title} 未配置 SHA256，无法安全下载。")

    with _DOWNLOAD_LOCK:
        existing = _DOWNLOADS.get(resource_id)
        if existing and existing.get("state") == "downloading":
            return get_runtime_resource_status(resource_id)
        _DOWNLOADS[resource_id] = _download_status("downloading", "准备下载资源。", 1)

    thread = threading.Thread(target=_download_resource_worker, args=(resource,), name=f"synpture-resource-{resource_id}", daemon=True)
    thread.start()
    return get_runtime_resource_status(resource_id)


def install_runtime_resource_file(resource_id: str, source_path: Path) -> dict[str, Any]:
    resource = get_runtime_resource(resource_id)
    if not source_path.exists():
        raise RuntimeError(f"文件不存在：{source_path}")

    if resource.sha256:
        actual = _sha256_file(source_path)
        if actual != resource.sha256:
            raise RuntimeError(f"SHA256 校验失败：{actual}")

    if resource.archive:
        _extract_archive(source_path, resource.target_path)
    else:
        resource.target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, resource.target_path)

    with _DOWNLOAD_LOCK:
        _DOWNLOADS[resource_id] = _download_status("ready", "资源已从本地文件安装。", 100)
    return get_runtime_resource_status(resource_id)


def runtime_resource_paths() -> dict[str, Path]:
    data_root = get_user_data_root()
    return {
        "model": data_root / "models" / "ggml-large-v3-turbo-q5_0.bin",
        "ffmpeg": data_root / "third_party" / "transcription_runtime" / "ffmpeg" / "bin" / "ffmpeg.exe",
        "ffprobe": data_root / "third_party" / "transcription_runtime" / "ffmpeg" / "bin" / "ffprobe.exe",
        "whisper_gpu": data_root / "third_party" / "transcription_runtime" / "whisper.cpp" / "build-cuda" / "bin" / "whisper-cli.exe",
        "whisper_cpu": data_root / "third_party" / "transcription_runtime" / "whisper.cpp" / "build-core" / "bin" / "whisper-cli.exe",
        "node": data_root / "third_party" / "browser_runtime" / "node" / "node.exe",
        "node_modules": data_root / "third_party" / "browser_runtime" / "node_runtime" / "node_modules",
        "chromium": data_root / "third_party" / "browser_runtime" / "chromium" / "chrome.exe",
    }


def effective_runtime_resource_paths() -> dict[str, Path]:
    resources = {resource.id: resource for resource in load_runtime_resources()}
    paths = runtime_resource_paths()

    model_resource = resources.get("model")
    if model_resource:
        paths["model"] = _effective_target_path(model_resource)

    transcription_resource = resources.get("transcription_runtime")
    if transcription_resource:
        transcription_root = _effective_target_path(transcription_resource)
        paths.update(
            {
                "ffmpeg": transcription_root / "ffmpeg" / "bin" / "ffmpeg.exe",
                "ffprobe": transcription_root / "ffmpeg" / "bin" / "ffprobe.exe",
                "whisper_gpu": transcription_root / "whisper.cpp" / "build-cuda" / "bin" / "whisper-cli.exe",
                "whisper_cpu": transcription_root / "whisper.cpp" / "build-core" / "bin" / "whisper-cli.exe",
            }
        )

    browser_resource = resources.get("browser_runtime")
    if browser_resource:
        browser_root = _effective_target_path(browser_resource)
        paths.update(
            {
                "node": browser_root / "node" / "node.exe",
                "node_modules": browser_root / "node_runtime" / "node_modules",
                "chromium": browser_root / "chromium" / "chrome.exe",
            }
        )

    return paths


def _resource_file_name(resource: RuntimeResource) -> str:
    if resource.url:
        parsed = urlparse(resource.url)
        name = unquote(Path(parsed.path).name)
        if name:
            return name
    return Path(resource.target).name


def _download_resource_worker(resource: RuntimeResource) -> None:
    temp_root = user_data_path("downloads")
    temp_root.mkdir(parents=True, exist_ok=True)
    suffix = ".zip" if resource.archive else Path(resource.target).suffix
    temp_path = temp_root / f"{resource.id}{suffix}.download"
    final_download = temp_root / f"{resource.id}{suffix}"
    try:
        _set_download_status(resource.id, "downloading", "正在下载资源。", 5)
        _download_file(resource.url, temp_path, resource.id)
        actual = _sha256_file(temp_path)
        if actual != resource.sha256:
            raise RuntimeError(f"SHA256 校验失败：{actual}")
        temp_path.replace(final_download)
        _set_download_status(resource.id, "installing", "正在安装资源。", 85)
        if resource.archive:
            _extract_archive(final_download, resource.target_path)
        else:
            resource.target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(final_download, resource.target_path)
        _set_download_status(resource.id, "ready", "资源已安装。", 100)
    except Exception as exc:
        _set_download_status(resource.id, "error", "资源下载或安装失败。", 0, error=str(exc))
    finally:
        temp_path.unlink(missing_ok=True)


def _download_file(url: str, destination: Path, resource_id: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "SynptureRuntimeDownloader"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while True:
            chunk = response.read(1024 * 512)
            if not chunk:
                break
            handle.write(chunk)
            received += len(chunk)
            if total:
                progress = max(5, min(80, int(received * 80 / total)))
                _set_download_status(resource_id, "downloading", "正在下载资源。", progress)


def _effective_target_path(resource: RuntimeResource) -> Path:
    source_paths = _dev_source_ready_paths(resource)
    if source_paths and all(path.exists() for path in source_paths):
        source_root = _dev_source_target_path(resource)
        if source_root is not None:
            return source_root
    return resource.target_path


def _effective_ready_paths(resource: RuntimeResource) -> tuple[Path, ...]:
    source_paths = _dev_source_ready_paths(resource)
    if source_paths and all(path.exists() for path in source_paths):
        return source_paths
    return resource.ready_paths


def _dev_source_target_path(resource: RuntimeResource) -> Path | None:
    if not _allow_dev_source_layout():
        return None
    layout = _DEV_SOURCE_LAYOUTS.get(resource.id)
    if not layout:
        return None
    target, _ = layout
    return get_app_root() / target


def _dev_source_ready_paths(resource: RuntimeResource) -> tuple[Path, ...]:
    source_target = _dev_source_target_path(resource)
    if source_target is None:
        return ()
    layout = _DEV_SOURCE_LAYOUTS.get(resource.id)
    if not layout:
        return ()
    _, markers = layout
    if markers:
        return tuple(source_target / marker for marker in markers)
    return (source_target,)


def _allow_dev_source_layout() -> bool:
    if is_packaged():
        return False
    try:
        return runtime_paths.get_user_data_root().resolve() == get_app_root().resolve()
    except OSError:
        return False


def _extract_archive(archive_path: Path, target_path: Path) -> None:
    if target_path.exists():
        shutil.rmtree(target_path)
    target_path.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(target_path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _set_download_status(resource_id: str, state: str, detail: str, progress: int, *, error: str | None = None) -> None:
    with _DOWNLOAD_LOCK:
        _DOWNLOADS[resource_id] = _download_status(state, detail, progress, error=error)


def _download_status(state: str, detail: str, progress: int, *, error: str | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "detail": detail,
        "progressPercent": progress,
        "error": error,
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
