from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.config import Settings
from src.link_ingest.platforms import detect_platform
from src.link_ingest.yt_dlp_client import YtDlpClient
from src.runtime_paths import bundled_path, get_app_root, get_managed_auth_root, runtime_resource_path
from src.utils import ensure_directory, hidden_subprocess_kwargs, run_command, slugify_filename, write_json


ProgressHook = Callable[[str], None]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)
DEFAULT_CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DEFAULT_NODE_BIN = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
DEFAULT_NODE_MODULES = (
    Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "node_modules"
)
MANAGED_AUTH_ROOT = get_managed_auth_root()
MANAGED_AUTH_START_URLS = {
    "douyin": "https://www.douyin.com/",
    "bilibili": "https://www.bilibili.com/",
}
MANAGED_AUTH_LABELS = {
    "douyin": "抖音",
    "bilibili": "B站",
}


@dataclass
class ShareLinkIngestResult:
    platform: str
    source_url: str
    resolved_url: str | None
    title: str | None
    local_media_path: Path
    method: str
    notes: list[str] = field(default_factory=list)
    artifacts: dict[str, Path] = field(default_factory=dict)


def ingest_share_link(
    *,
    share_url: str,
    run_dir: Path,
    settings: Settings,
    browser_profiles: dict[str, str | None] | None = None,
    progress_hook: ProgressHook | None = None,
) -> ShareLinkIngestResult:
    url = share_url.strip()
    if not url:
        raise RuntimeError("分享链接不能为空。")

    platform = detect_platform(url)
    notes: list[str] = []
    browser_profiles = browser_profiles or {}

    _notify(progress_hook, f"正在识别分享链接平台：{platform}")
    ingest_dir = ensure_directory(run_dir / "share_link_ingest")

    if platform == "xiaohongshu":
        return _ingest_xiaohongshu(url=url, ingest_dir=ingest_dir, notes=notes, progress_hook=progress_hook)
    if platform == "douyin":
        user_data_dir_value = browser_profiles.get("douyin")
        if not user_data_dir_value:
            raise RuntimeError("抖音分享链接需要先打开一次工具内的抖音授权浏览器并完成登录。")
        return _ingest_douyin(
            url=url,
            ingest_dir=ingest_dir,
            auth_user_data_dir=Path(user_data_dir_value),
            notes=notes,
            progress_hook=progress_hook,
        )
    if platform == "bilibili":
        return _ingest_bilibili(
            url=url,
            ingest_dir=ingest_dir,
            auth_user_data_dir=Path(browser_profiles["bilibili"]) if browser_profiles.get("bilibili") else None,
            notes=notes,
            progress_hook=progress_hook,
        )

    raise RuntimeError(f"暂不支持这个分享链接平台：{platform}")


def _ingest_xiaohongshu(
    *,
    url: str,
    ingest_dir: Path,
    notes: list[str],
    progress_hook: ProgressHook | None,
) -> ShareLinkIngestResult:
    client = YtDlpClient()
    _notify(progress_hook, "正在用匿名模式解析小红书分享链接")
    metadata = client.extract_info(url)
    metadata_path = write_json(ingest_dir / "metadata.json", metadata)

    _notify(progress_hook, "正在下载小红书视频")
    media_path = client.download_media(url=url, output_dir=ingest_dir, media_kind="video")
    final_path = ingest_dir / f"{slugify_filename(metadata.get('title') or 'xiaohongshu_share')}{media_path.suffix or '.mp4'}"
    media_path.replace(final_path)

    notes.append("小红书走匿名 yt-dlp 直连下载。")
    return ShareLinkIngestResult(
        platform="xiaohongshu",
        source_url=url,
        resolved_url=str(metadata.get("webpage_url") or url),
        title=str(metadata.get("title") or "") or None,
        local_media_path=final_path,
        method="yt_dlp_anonymous_video",
        notes=notes,
        artifacts={"metadata": metadata_path},
    )


def _ingest_douyin(
    *,
    url: str,
    ingest_dir: Path,
    auth_user_data_dir: Path,
    notes: list[str],
    progress_hook: ProgressHook | None,
) -> ShareLinkIngestResult:
    user_data_dir = resolve_managed_auth_user_data_dir("douyin", auth_user_data_dir)
    _notify(progress_hook, f"正在加载抖音工具内授权会话：{user_data_dir}")
    notes.append(f"抖音使用工具内授权浏览器：{user_data_dir}")

    probe_dir = ensure_directory(ingest_dir / "probe_douyin")
    _notify(progress_hook, "正在启动浏览器探针解析抖音页面")
    report = run_browser_probe(
        platform="douyin",
        share_url=url,
        output_dir=probe_dir,
        user_data_dir=user_data_dir,
    )

    media_url = str(report.get("bestMediaUrl") or "")
    if not media_url:
        raise RuntimeError("抖音探针没有拿到可下载的视频地址。")

    output_path = ingest_dir / "douyin_source.mp4"
    _notify(progress_hook, "正在下载抖音视频")
    download_url(
        media_url,
        output_path,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": str(report.get("finalUrl") or url),
        },
    )

    notes.append("抖音走浏览器探针直取可播放视频地址。")
    return ShareLinkIngestResult(
        platform="douyin",
        source_url=url,
        resolved_url=str(report.get("finalUrl") or url),
        title=str(report.get("finalTitle") or "") or None,
        local_media_path=output_path,
        method="browser_probe_video_url",
        notes=notes,
        artifacts={"probe_report": probe_dir / "report.json", "probe_html": probe_dir / "page.html", "probe_screenshot": probe_dir / "page.png"},
    )


def _ingest_bilibili(
    *,
    url: str,
    ingest_dir: Path,
    auth_user_data_dir: Path | None,
    notes: list[str],
    progress_hook: ProgressHook | None,
) -> ShareLinkIngestResult:
    probe_kwargs: dict[str, object] = {}
    if auth_user_data_dir:
        try:
            user_data_dir = resolve_managed_auth_user_data_dir("bilibili", auth_user_data_dir)
            notes.append(f"B站使用工具内授权浏览器：{user_data_dir}")
            probe_kwargs["user_data_dir"] = user_data_dir
        except Exception as exc:
            notes.append(f"B站工具内授权会话不可用，已退回匿名浏览器探针：{exc}")

    probe_dir = ensure_directory(ingest_dir / "probe_bilibili")
    _notify(progress_hook, "正在启动浏览器探针解析 B站页面")
    report = run_browser_probe(
        platform="bilibili",
        share_url=url,
        output_dir=probe_dir,
        **probe_kwargs,
    )

    audio_url = str(report.get("bestAudioUrl") or "")
    media_url = audio_url or str(report.get("bestMediaUrl") or report.get("bestVideoUrl") or "")
    if not media_url:
        raise RuntimeError("B站探针没有拿到可下载的媒体地址。")

    suffix = ".m4a" if audio_url else ".mp4"
    output_path = ingest_dir / f"bilibili_source{suffix}"
    _notify(progress_hook, "正在下载 B站媒体流")
    download_url(
        media_url,
        output_path,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": str(report.get("finalUrl") or url),
        },
    )

    if audio_url:
        notes.append("B站走浏览器探针并直接提取音轨，避免 412 和视频流合并问题。")
    else:
        notes.append("B站走浏览器探针并回退到页面捕获到的媒体流。")
    return ShareLinkIngestResult(
        platform="bilibili",
        source_url=url,
        resolved_url=str(report.get("finalUrl") or url),
        title=str(report.get("finalTitle") or "") or None,
        local_media_path=output_path,
        method="browser_probe_audio_url" if audio_url else "browser_probe_media_url",
        notes=notes,
        artifacts={"probe_report": probe_dir / "report.json", "probe_html": probe_dir / "page.html", "probe_screenshot": probe_dir / "page.png"},
    )


def get_managed_auth_user_data_dir(platform: str) -> Path:
    if platform not in MANAGED_AUTH_START_URLS:
        raise RuntimeError(f"暂不支持这个授权平台：{platform}")
    return ensure_directory(MANAGED_AUTH_ROOT / platform / "chrome_user_data")


def resolve_managed_auth_user_data_dir(platform: str, auth_user_data_dir: Path | None) -> Path:
    user_data_dir = auth_user_data_dir or get_managed_auth_user_data_dir(platform)
    if not user_data_dir.exists():
        raise RuntimeError(f"{MANAGED_AUTH_LABELS[platform]} 尚未建立工具内授权目录。请先点击“打开授权浏览器”。")
    default_profile_dir = user_data_dir / "Default"
    if not default_profile_dir.exists():
        raise RuntimeError(f"{MANAGED_AUTH_LABELS[platform]} 尚未完成工具内登录。请先点击“打开授权浏览器”并在弹出的窗口里完成登录。")
    return user_data_dir


def launch_managed_auth_browser(platform: str) -> Path:
    user_data_dir = get_managed_auth_user_data_dir(platform)
    script_path = bundled_path("tools", "share_link_auth_browser.js")
    if not script_path.exists():
        raise RuntimeError(f"未找到授权浏览器脚本：{script_path}")

    node_bin = resolve_node_bin()
    env = build_node_env()
    command = [
        node_bin,
        str(script_path),
        "--platform",
        platform,
        "--user-data-dir",
        str(user_data_dir),
        "--start-url",
        MANAGED_AUTH_START_URLS[platform],
    ]

    creation_flags = 0
    creation_flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    creation_flags |= getattr(subprocess, "DETACHED_PROCESS", 0)

    subprocess.Popen(
        command,
        cwd=str(get_app_root()),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )
    return user_data_dir


def inspect_managed_auth_profile(platform: str) -> dict[str, object]:
    user_data_dir = get_managed_auth_user_data_dir(platform)
    profile_dir = user_data_dir / "Default"
    cookies_path = profile_dir / "Network" / "Cookies"
    fallback_cookies_path = profile_dir / "Cookies"
    rules = {
        "douyin": {
            "domains": ["%douyin.com%", "%iesdouyin.com%"],
            "critical_cookie_names": {"sessionid_ss", "sessionid", "passport_csrf_token"},
        },
        "bilibili": {
            "domains": ["%bilibili.com%"],
            "critical_cookie_names": {"SESSDATA", "DedeUserID", "bili_jct"},
        },
    }
    label = MANAGED_AUTH_LABELS[platform]
    rule = rules[platform]

    if not profile_dir.exists():
        return {
            "ok": False,
            "tone": "pending",
            "statusLabel": "待授权",
            "summary": f"{label} 还没有建立授权会话。",
            "details": [
                "还没有找到授权文件。",
                "请点击“打开授权”，在弹出的浏览器里完成登录。",
            ],
        }

    active_cookies_path = cookies_path if cookies_path.exists() else fallback_cookies_path
    if not active_cookies_path.exists():
        return {
            "ok": False,
            "tone": "pending",
            "statusLabel": "待授权",
            "summary": f"{label} 还没有生成可检查的授权文件。",
            "details": [
                "没有检测到 Cookies 数据库。",
                "请先点击“打开授权”，完成登录后再检查状态。",
            ],
        }

    matched_cookie_names: set[str] = set()
    matched_domains: set[str] = set()
    total_matches = 0
    temp_dir = Path()
    temp_cookies = Path()
    conn: sqlite3.Connection | None = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="mp4_managed_auth_check_"))
        temp_cookies = temp_dir / "Cookies"
        shutil.copy2(active_cookies_path, temp_cookies)
        conn = sqlite3.connect(temp_cookies)
        for domain_like in rule["domains"]:
            rows = conn.execute(
                "SELECT host_key, name FROM cookies WHERE host_key LIKE ?",
                (domain_like,),
            ).fetchall()
            for host_key, name in rows:
                total_matches += 1
                if host_key:
                    matched_domains.add(str(host_key))
                if name:
                    matched_cookie_names.add(str(name))
    except PermissionError:
        return {
            "ok": False,
            "tone": "offline",
            "statusLabel": "检查失败",
            "summary": f"{label} 当前无法完成状态检查。",
            "details": [
                "授权浏览器窗口可能还开着，Cookies 文件正被占用。",
                "请先关闭授权浏览器，再点击“检查状态”。",
            ],
        }
    finally:
        if conn is not None:
            conn.close()
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    critical_hits = sorted(rule["critical_cookie_names"].intersection(matched_cookie_names))
    critical_missing = sorted(rule["critical_cookie_names"].difference(matched_cookie_names))
    details: list[str] = []

    if critical_hits and not critical_missing:
        details.append("关键登录信息完整，可以直接执行链接转录。")
        return {
            "ok": True,
            "tone": "ready",
            "statusLabel": "可用",
            "summary": f"{label} 工具内授权已就绪，可以直接跑分享链接转录。",
            "details": details,
        }

    if total_matches > 0:
        if critical_missing:
            details.append("缺少关键登录信息：" + "、".join(critical_missing))
        if critical_hits:
            details.append("只识别到部分登录信息：" + "、".join(critical_hits))
        details.append("检测到平台访问痕迹，但登录态不完整，当前授权不可用。")
        return {
            "ok": False,
            "tone": "offline",
            "statusLabel": "授权失效",
            "summary": f"{label} 登录态不完整，当前授权不可用。",
            "details": details,
        }

    details.append("没有检测到该平台的登录信息。")
    details.append("请点击“打开授权”，登录后再重新检查。")
    return {
        "ok": False,
        "tone": "offline",
        "statusLabel": "检查失败",
        "summary": f"{label} 没有检测到可用的登录信息。",
        "details": details,
    }


def run_browser_probe(
    *,
    platform: str,
    share_url: str,
    output_dir: Path,
    profile_dir: str | None = None,
    user_data_dir: Path | None = None,
    headless: bool = True,
    timeout_ms: int = 45000,
) -> dict[str, object]:
    ensure_directory(output_dir)
    script_path = bundled_path("tools", "share_link_browser_probe.js")
    if not script_path.exists():
        raise RuntimeError(f"未找到浏览器探针脚本：{script_path}")

    node_bin = resolve_node_bin()
    env = build_node_env()
    command = [
        node_bin,
        str(script_path),
        "--platform",
        platform,
        "--share-url",
        share_url,
        "--output-dir",
        str(output_dir),
        "--timeout-ms",
        str(timeout_ms),
    ]
    if headless:
        command.append("--headless")
    if profile_dir:
        command.extend(["--profile-dir", profile_dir])
    if user_data_dir:
        command.extend(["--user-data-dir", str(user_data_dir)])

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **hidden_subprocess_kwargs(),
    )
    report_path = output_dir / "report.json"
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "浏览器探针执行失败。"
        raise RuntimeError(details)
    if not report_path.exists():
        raise RuntimeError("浏览器探针执行完成，但没有生成 report.json。")
    return json.loads(report_path.read_text(encoding="utf-8"))


def download_url(url: str, output_path: Path, headers: dict[str, str] | None = None) -> Path:
    request_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=120) as response, output_path.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return output_path


def resolve_node_bin() -> str:
    env_value = os.getenv("SHARE_LINK_NODE_BIN")
    if env_value:
        return env_value
    runtime_node = runtime_resource_path("third_party", "browser_runtime", "node", "node.exe")
    if runtime_node.exists():
        return str(runtime_node)
    bundled_node = bundled_path("third_party", "node", "node.exe")
    if bundled_node.exists():
        return str(bundled_node)
    if DEFAULT_NODE_BIN.exists():
        return str(DEFAULT_NODE_BIN)
    return shutil.which("node") or "node"


def build_node_env() -> dict[str, str]:
    env = dict(os.environ)
    runtime_node_modules = runtime_resource_path("third_party", "browser_runtime", "node_runtime", "node_modules")
    bundled_node_modules = bundled_path("third_party", "node_runtime", "node_modules")
    legacy_bundled_node_modules = bundled_path("third_party", "node", "node_modules")
    node_path_candidates = [
        os.getenv("SHARE_LINK_NODE_PATH"),
        str(runtime_node_modules) if runtime_node_modules.exists() else None,
        str(bundled_node_modules) if bundled_node_modules.exists() else None,
        str(legacy_bundled_node_modules) if legacy_bundled_node_modules.exists() else None,
        str(DEFAULT_NODE_MODULES) if DEFAULT_NODE_MODULES.exists() else None,
    ]
    node_path_values = [value for value in node_path_candidates if value]
    if node_path_values:
        existing = env.get("NODE_PATH")
        if existing:
            node_path_values.append(existing)
        env["NODE_PATH"] = os.pathsep.join(node_path_values)
    runtime_chromium = runtime_resource_path("third_party", "browser_runtime", "chromium", "chrome.exe")
    bundled_chromium = bundled_path("third_party", "chromium", "chrome.exe")
    if runtime_chromium.exists():
        env.setdefault("SHARE_LINK_CHROME_EXE", str(runtime_chromium))
    if bundled_chromium.exists():
        env.setdefault("SHARE_LINK_CHROME_EXE", str(bundled_chromium))
    if DEFAULT_CHROME_PATH.exists():
        env.setdefault("SHARE_LINK_CHROME_EXE", str(DEFAULT_CHROME_PATH))
    return env


def merge_media_with_ffmpeg(
    *,
    settings: Settings,
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    run_command(
        [
            settings.ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-c",
            "copy",
            str(output_path),
        ],
        "ffmpeg 合并音视频失败",
    )
    return output_path


def _notify(progress_hook: ProgressHook | None, detail: str) -> None:
    if progress_hook:
        progress_hook(detail)
