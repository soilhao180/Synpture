from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from src.config import Settings
from src.runtime_paths import (
    bundled_path,
    get_env_path,
    get_managed_auth_root,
    get_user_data_root,
    get_windows_debug_crt_dependencies,
    is_packaged,
    runtime_resource_path,
)
from src.runtime_resources import serialize_runtime_resources
from src.runtime_resources import effective_runtime_resource_paths
from src.transcription_runtime import probe_transcription_capability
from src.utils import ensure_directory, hidden_subprocess_kwargs


@dataclass
class DiagnosticItem:
    name: str
    status: str
    detail: str
    recommendation: str | None = None


def run_startup_checks(settings: Settings) -> list[DiagnosticItem]:
    return [
        check_workspace_runtime_mode(),
        check_python_version(),
        check_binary("ffmpeg", settings.ffmpeg_bin),
        check_binary("ffprobe", settings.ffprobe_bin),
        check_binary("whisper.cpp", settings.whisper_cpp_bin),
        check_whisper_cpp_portability(settings),
        check_model_file(settings.whisper_cpp_model_path),
        check_packaged_runtime_paths(settings),
        check_runtime_resources(),
        check_browser_runtime(),
        check_python_package("openai", "openai"),
        check_python_package("python-dotenv", "dotenv", optional=True),
        check_output_directory(settings.output_dir),
        check_local_transcription_capability(settings),
        check_gpu_environment(),
        check_api_config(
            name="API 总结配置",
            api_key=settings.summary_api_key,
            model=settings.summary_api_model,
            base_url=settings.summary_api_base_url,
            backend_note="总结阶段使用独立模型配置",
        ),
    ]


def check_workspace_runtime_mode() -> DiagnosticItem:
    if is_packaged():
        return DiagnosticItem(
            "工作台架构",
            "ok",
            "当前安装版正在使用 FastAPI + workspace-ui 主工作台；旧 Streamlit 工作台不是安装版必需项。",
        )
    return DiagnosticItem(
        "工作台架构",
        "ok",
        "当前开发模式正在使用 FastAPI + workspace-ui 主工作台，默认入口仍为 python app.py。",
    )


def check_packaged_runtime_paths(settings: Settings) -> DiagnosticItem:
    if not is_packaged():
        return DiagnosticItem(
            "安装包运行时",
            "ok",
            f"当前为开发模式；配置文件：{get_env_path()}；输出目录：{settings.output_dir}",
        )

    data_root = get_user_data_root()
    auth_root = get_managed_auth_root()
    try:
        ensure_directory(data_root)
        ensure_directory(auth_root)
    except Exception as exc:
        return DiagnosticItem(
            "安装包运行时",
            "error",
            f"用户数据目录不可写：{data_root} ({exc})",
            "请检查当前用户的 AppData 目录权限，或用 SYNPTURE_DATA_DIR 指定可写目录。",
        )

    return DiagnosticItem(
        "安装包运行时",
        "ok",
        f"用户数据目录可用：{data_root}；授权目录：{auth_root}",
    )


def check_browser_runtime() -> DiagnosticItem:
    resource_paths = effective_runtime_resource_paths()
    node_bin = os.getenv("SHARE_LINK_NODE_BIN")
    node_candidates = [
        Path(node_bin) if node_bin else None,
        resource_paths.get("node"),
        runtime_resource_path("third_party", "browser_runtime", "node", "node.exe"),
        bundled_path("third_party", "node", "node.exe"),
        shutil.which("node"),
    ]
    node_ready = any(Path(str(candidate)).exists() for candidate in node_candidates if candidate)

    node_path = os.getenv("SHARE_LINK_NODE_PATH")
    node_modules_candidates = [
        Path(node_path) if node_path else None,
        resource_paths.get("node_modules"),
        runtime_resource_path("third_party", "browser_runtime", "node_runtime", "node_modules"),
        bundled_path("third_party", "node_runtime", "node_modules"),
        bundled_path("third_party", "node", "node_modules"),
    ]
    playwright_ready = any((Path(str(candidate)) / "playwright").exists() for candidate in node_modules_candidates if candidate)

    chrome_env = os.getenv("SHARE_LINK_CHROME_EXE")
    chrome_candidates = [
        Path(chrome_env) if chrome_env else None,
        resource_paths.get("chromium"),
        runtime_resource_path("third_party", "browser_runtime", "chromium", "chrome.exe"),
        bundled_path("third_party", "chromium", "chrome.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ]
    chrome_ready = any(Path(str(candidate)).exists() for candidate in chrome_candidates if candidate)

    if node_ready and playwright_ready and chrome_ready:
        return DiagnosticItem("授权浏览器运行时", "ok", "Node、Playwright 和 Chrome/Chromium 均可用。")

    missing = []
    if not node_ready:
        missing.append("Node")
    if not playwright_ready:
        missing.append("Playwright")
    if not chrome_ready:
        missing.append("Chrome/Chromium")
    return DiagnosticItem(
        "授权浏览器运行时",
        "warn",
        f"分享链接授权/探针可能不可用，缺少：{', '.join(missing)}。",
        "安装包应内置 third_party/node 与 third_party/chromium，或在 .env 中配置 SHARE_LINK_NODE_BIN/SHARE_LINK_NODE_PATH/SHARE_LINK_CHROME_EXE。",
    )


def check_runtime_resources() -> DiagnosticItem:
    resources = serialize_runtime_resources()
    if not resources:
        return DiagnosticItem("运行资源", "warn", "未找到运行资源 manifest。", "请检查 packaging/runtime_resources.json。")

    invalid = [item["title"] for item in resources if item.get("state") == "invalid"]
    missing = [item["title"] for item in resources if not item.get("ready")]
    if invalid:
        return DiagnosticItem("运行资源", "error", f"资源校验失败：{', '.join(invalid)}。", "请重新下载对应运行资源。")
    if missing:
        return DiagnosticItem("运行资源", "warn", f"缺少运行资源：{', '.join(missing)}。", "在健康自检中下载缺失资源后可继续使用。")
    return DiagnosticItem("运行资源", "ok", "模型、授权浏览器运行时和本地转录运行时均已安装。")


def overall_status(items: list[DiagnosticItem]) -> str:
    ranks = {"ok": 0, "warn": 1, "error": 2}
    highest = max((ranks.get(item.status, 0) for item in items), default=0)
    for label, rank in ranks.items():
        if rank == highest:
            return label
    return "ok"


def check_python_version(version_info: tuple[int, int, int] | None = None) -> DiagnosticItem:
    major, minor, micro = version_info or sys.version_info[:3]
    version_text = f"{major}.{minor}.{micro}"

    if (major, minor) == (3, 11):
        return DiagnosticItem("Python 版本", "ok", f"当前 Python 为 {version_text}，符合推荐版本。")
    if major == 3 and minor >= 11:
        return DiagnosticItem(
            "Python 版本",
            "warn",
            f"当前 Python 为 {version_text}，可以运行，但仍建议优先使用 3.11。",
            "如需最稳妥，建议使用 `py -3.11 -m venv .venv` 创建虚拟环境。",
        )
    return DiagnosticItem(
        "Python 版本",
        "error",
        f"当前 Python 为 {version_text}，不在推荐范围内。",
        "请安装 Python 3.11，并使用 `py -3.11 -m venv .venv` 创建虚拟环境。",
    )


def check_binary(name: str, binary: str) -> DiagnosticItem:
    resolved = str(Path(binary).resolve()) if Path(binary).exists() else shutil.which(binary)
    if resolved:
        return DiagnosticItem(name, "ok", f"已找到 {binary}: {resolved}")
    return DiagnosticItem(
        name,
        "error",
        f"未找到 {binary}。",
        f"请安装或配置 {name}，并确保它可执行，或在 .env 中填写正确路径。",
    )


def check_model_file(model_path: Path) -> DiagnosticItem:
    if model_path.exists():
        size_gb = model_path.stat().st_size / 1024 / 1024 / 1024
        return DiagnosticItem(
            "whisper.cpp 模型",
            "ok",
            f"已找到模型文件：{model_path}（约 {size_gb:.2f} GB）",
        )
    return DiagnosticItem(
        "whisper.cpp 模型",
        "error",
        f"未找到模型文件：{model_path}",
        "请先下载 whisper.cpp 模型，并在 .env 中设置 WHISPER_CPP_MODEL_PATH。",
    )


def check_whisper_cpp_portability(settings: Settings) -> DiagnosticItem:
    binary_path = Path(settings.whisper_cpp_bin)
    if not binary_path.exists():
        return DiagnosticItem(
            "whisper.cpp portability",
            "warn",
            f"whisper.cpp executable not found: {settings.whisper_cpp_bin}",
            "Point WHISPER_CPP_BIN to a valid release build of whisper-cli.exe before packaging or installing.",
        )

    debug_dependencies = get_windows_debug_crt_dependencies(binary_path)
    if not debug_dependencies:
        return DiagnosticItem(
            "whisper.cpp portability",
            "ok",
            f"{binary_path.name} does not reference Debug CRT DLLs.",
        )

    dependency_text = ", ".join(debug_dependencies)
    return DiagnosticItem(
        "whisper.cpp portability",
        "error",
        f"{binary_path.name} references Debug CRT DLLs: {dependency_text}",
        "Rebuild or replace the CUDA whisper.cpp runtime with a Release build before distributing this installer.",
    )


def check_python_package(display_name: str, import_name: str, optional: bool = False) -> DiagnosticItem:
    if importlib.util.find_spec(import_name):
        return DiagnosticItem(display_name, "ok", f"已安装 Python 包 `{display_name}`。")
    status = "warn" if optional else "error"
    recommendation = (
        "执行 `python -m pip install -r requirements.txt` 补齐依赖。"
        if not optional
        else "缺少可选依赖时仍可运行，但不会自动加载 .env 文件。"
    )
    detail = (
        f"未检测到 Python 包 `{display_name}`。"
        if not optional
        else f"未检测到可选包 `{display_name}`。"
    )
    return DiagnosticItem(display_name, status, detail, recommendation)


def check_output_directory(output_dir: Path) -> DiagnosticItem:
    try:
        ensure_directory(output_dir)
        probe_file = output_dir / ".write_test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
    except Exception as exc:
        return DiagnosticItem(
            "输出目录",
            "error",
            f"输出目录不可写：{output_dir} ({exc})",
            "请检查目录权限，或在 .env 中重新设置 OUTPUT_DIR。",
        )

    return DiagnosticItem("输出目录", "ok", f"输出目录可写：{output_dir}")


def check_local_transcription_capability(settings: Settings) -> DiagnosticItem:
    capability = probe_transcription_capability(settings)
    if capability.gpu_status == "ready":
        detail = (
            f"GPU 转录可用；模型 `{settings.whisper_cpp_model_path.name}`；"
            f"GPU 版 `{settings.whisper_cpp_bin}`。"
        )
        if capability.cpu_fallback_available:
            detail += " CPU 兼容模式也可作为显式兜底。"
        return DiagnosticItem("鏈湴杞綍閾捐矾", "ok", detail)

    if capability.cpu_fallback_available:
        recommendation = capability.gpu_reason
        if capability.gpu_recoverable:
            recommendation = f"{capability.gpu_reason} CPU 兼容模式可先继续使用。"
        return DiagnosticItem(
            "鏈湴杞綍閾捐矾",
            "warn",
            f"{capability.gpu_reason} {capability.cpu_reason}",
            recommendation,
        )

    return DiagnosticItem(
        "鏈湴杞綍閾捐矾",
        "error",
        f"{capability.gpu_reason} {capability.cpu_reason}",
        "请先补齐 whisper.cpp 运行时、模型文件与 ffmpeg，再开始转录。",
    )


def check_local_transcription(settings: Settings) -> DiagnosticItem:
    binary_ready = Path(settings.whisper_cpp_bin).exists() or shutil.which(settings.whisper_cpp_bin)
    model_ready = settings.whisper_cpp_model_path.exists()
    ffmpeg_ready = Path(settings.ffmpeg_bin).exists() or shutil.which(settings.ffmpeg_bin)

    if binary_ready and model_ready and ffmpeg_ready:
        return DiagnosticItem(
            "本地转录链路",
            "ok",
            (
                f"本地 whisper.cpp 转录条件已具备，模型 `{settings.whisper_cpp_model_path.name}`，"
                f"设备策略 `{settings.local_whisper_device}`。"
            ),
        )

    missing = []
    if not binary_ready:
        missing.append("whisper.cpp")
    if not model_ready:
        missing.append("模型文件")
    if not ffmpeg_ready:
        missing.append("ffmpeg")
    return DiagnosticItem(
        "本地转录链路",
        "error",
        f"本地转录暂不可用，缺少：{', '.join(missing)}。",
        "先补齐 whisper.cpp 二进制、模型文件与 ffmpeg，再开始转录。",
    )


def check_gpu_environment() -> DiagnosticItem:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return DiagnosticItem(
            "GPU 环境",
            "warn",
            "未找到 nvidia-smi，无法自动确认 GPU 状态。",
            "如果计划启用本地 GPU 转录，请确认显卡驱动和 CUDA 已安装。",
        )

    try:
        result = subprocess.run(
            [executable, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            **hidden_subprocess_kwargs(),
        )
    except Exception as exc:
        return DiagnosticItem(
            "GPU 环境",
            "warn",
            f"检测到 nvidia-smi，但读取 GPU 信息失败：{exc}",
            "请在终端单独执行 `nvidia-smi` 检查驱动和 CUDA 运行状态。",
        )

    first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not first_line:
        return DiagnosticItem(
            "GPU 环境",
            "warn",
            "nvidia-smi 可执行，但没有返回 GPU 详情。",
            "请在终端单独执行 `nvidia-smi` 检查显卡状态。",
        )

    return DiagnosticItem("GPU 环境", "ok", f"检测到 GPU：{first_line}")


def check_api_config(
    name: str,
    api_key: str | None,
    model: str | None,
    base_url: str | None,
    backend_note: str,
) -> DiagnosticItem:
    if api_key and model:
        base_text = base_url or "默认地址"
        return DiagnosticItem(
            name,
            "ok",
            f"{backend_note}；模型 `{model}`，请求地址 `{base_text}`。",
        )

    if model and not api_key:
        return DiagnosticItem(
            name,
            "warn",
            f"已配置模型 `{model}`，但缺少 API Key。",
            "补充 API Key 后即可启用远程总结。",
        )

    return DiagnosticItem(
        name,
        "warn",
        f"{backend_note}；当前尚未完整配置该 API 链路。",
        "如果你希望使用远程模型，请在 .env 中填写 base_url、api_key 和 model。",
    )
