from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from src.presentation.web_app import FrontendSessionTracker, create_web_app
from src.server_boot import create_uvicorn_server, resolve_server_port

PENDING_OPEN_TIMEOUT_SECONDS = 6.0
STATE_INACTIVE = "inactive"
STATE_PENDING_OPEN = "pending-open"
STATE_ACTIVE = "active"


@dataclass
class FrontendLifecycleState:
    state: str = STATE_INACTIVE
    pending_until: float = 0.0
    active_count: int = 0


class SynptureLauncherApp:
    def __init__(self) -> None:
        self.host = os.getenv("SYNPTURE_HOST", "127.0.0.1")
        self.preferred_port = int(os.getenv("SYNPTURE_PORT", "8000"))
        self.frontend_sessions = FrontendSessionTracker()
        self.server = None
        self.server_thread: threading.Thread | None = None
        self.url = ""
        self._shutdown_started = False
        self._icon: Any | None = None
        self._attached_to_existing_server = False
        self._lifecycle = FrontendLifecycleState()

    def run(self) -> None:
        existing_port = _find_running_server_port(self.host, self.preferred_port)
        if existing_port is not None:
            self.url = f"http://{self.host}:{existing_port}/"
            self._attached_to_existing_server = True
            if _should_open_browser() and self._normalized_frontend_state().state == STATE_INACTIVE:
                self.open_browser_if_needed(force=True)
            self._run_tray()
            return

        port = resolve_server_port(self.host, self.preferred_port)
        self.url = f"http://{self.host}:{port}/"
        self.server = create_uvicorn_server(
            create_web_app(self.frontend_sessions, shutdown_handler=self.shutdown),
            host=self.host,
            port=port,
        )
        self.server_thread = threading.Thread(target=self.server.run, name="synpture-uvicorn", daemon=True)
        self.server_thread.start()

        _wait_for_server(self.host, port)
        if _should_open_browser():
            self.open_browser_if_needed(force=True)

        self._run_tray()

    def open_browser_if_needed(self, *, force: bool = False) -> bool:
        if not self.url:
            return False
        if not force and self._normalized_frontend_state().state != STATE_INACTIVE:
            return False
        self._mark_pending_open()
        webbrowser.open(self.url)
        return True

    def force_open_browser(self) -> bool:
        if not self.url:
            return False
        self._mark_pending_open()
        webbrowser.open(self.url)
        return True

    def shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        if self._attached_to_existing_server and self.url:
            _request_remote_shutdown(self.url)
        if self.server is not None:
            self.server.should_exit = True
        if self.server_thread is not None and self.server_thread.is_alive():
            self.server_thread.join(timeout=5)
        if self._icon is not None:
            self._icon.stop()

    def _run_tray(self) -> None:
        if not _supports_tray():
            try:
                while self._runtime_alive():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                self.shutdown()
            return

        pystray_module = _load_pystray()
        icon = pystray_module.Icon("synpture", _load_tray_image(), "Synpture")
        self._icon = icon

        def open_action(tray_icon, item) -> None:
            self.open_browser_if_needed()
            tray_icon.update_menu()

        def force_open_action(tray_icon, item) -> None:
            self.force_open_browser()
            tray_icon.update_menu()

        def exit_action(tray_icon, item) -> None:
            self.shutdown()

        icon.menu = pystray_module.Menu(
            pystray_module.MenuItem(
                "打开 Synpture",
                open_action,
                enabled=lambda item: self._normalized_frontend_state().state == STATE_INACTIVE,
                default=True,
            ),
            pystray_module.MenuItem("强制重新打开前端", force_open_action),
            pystray_module.MenuItem(
                lambda item: _build_session_status_label(self._normalized_frontend_state()),
                lambda tray_icon, item: None,
                enabled=False,
            ),
            pystray_module.Menu.SEPARATOR,
            pystray_module.MenuItem("退出 Synpture", exit_action),
        )

        watcher = threading.Thread(target=self._watch_tray_state, name="synpture-tray-watch", daemon=True)
        watcher.start()

        try:
            icon.run()
        finally:
            self.shutdown()

    def _watch_tray_state(self) -> None:
        while not self._shutdown_started and self._runtime_alive():
            self._normalized_frontend_state()
            time.sleep(1.0)
            try:
                if self._icon is not None:
                    self._icon.update_menu()
            except Exception:
                return
        if not self._shutdown_started:
            self.shutdown()

    def _runtime_alive(self) -> bool:
        if self._attached_to_existing_server:
            return _is_url_alive(self.url)
        return bool(self.server_thread and self.server_thread.is_alive())

    def _mark_pending_open(self) -> None:
        self._lifecycle.state = STATE_PENDING_OPEN
        self._lifecycle.pending_until = time.time() + PENDING_OPEN_TIMEOUT_SECONDS
        self._lifecycle.active_count = 0

    def _normalized_frontend_state(self) -> FrontendLifecycleState:
        snapshot = self._session_snapshot()
        active = bool(snapshot.get("active"))
        session_count = int(snapshot.get("sessionCount") or 0)
        now = time.time()

        if active:
            self._lifecycle.state = STATE_ACTIVE
            self._lifecycle.pending_until = 0.0
            self._lifecycle.active_count = session_count
            return self._lifecycle

        if self._lifecycle.state == STATE_PENDING_OPEN and now < self._lifecycle.pending_until:
            self._lifecycle.active_count = 0
            return self._lifecycle

        self._lifecycle.state = STATE_INACTIVE
        self._lifecycle.pending_until = 0.0
        self._lifecycle.active_count = 0
        return self._lifecycle

    def _session_snapshot(self) -> dict[str, object]:
        if self._attached_to_existing_server:
            return _fetch_remote_session_snapshot(self.url)
        return self.frontend_sessions.snapshot()


def main() -> None:
    SynptureLauncherApp().run()


def _wait_for_server(host: str, port: int, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _is_port_open(host, port):
            return
        time.sleep(0.2)
    raise RuntimeError(f"Synpture server did not start within {timeout_seconds:.0f}s on {host}:{port}")


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _find_running_server_port(host: str, preferred_port: int, max_attempts: int = 20) -> int | None:
    for port in range(preferred_port, preferred_port + max_attempts):
        if _is_port_open(host, port):
            return port
    return None


def _should_open_browser() -> bool:
    value = os.getenv("SYNPTURE_NO_BROWSER", "").strip().lower()
    return value not in {"1", "true", "yes", "on"}


def _supports_tray() -> bool:
    value = os.getenv("SYNPTURE_DISABLE_TRAY", "").strip().lower()
    return value not in {"1", "true", "yes", "on"}


def _build_session_status_label(state: FrontendLifecycleState) -> str:
    if state.state == STATE_ACTIVE:
        return f"前端已打开 ({state.active_count})"
    if state.state == STATE_PENDING_OPEN:
        return "正在等待前端连接"
    return "前端未打开"


def _load_tray_image():
    Image_module, ImageDraw_module = _load_pillow()
    branding_png_path = Path(__file__).resolve().parent / "assets" / "branding" / "synpture-tray.png"
    if branding_png_path.exists():
        try:
            return Image_module.open(branding_png_path).convert("RGBA")
        except Exception:
            pass

    logo_path = Path(__file__).resolve().parent / "workspace-ui" / "assets" / "icons" / "start-page-logo.svg"
    if logo_path.exists():
        try:
            import cairosvg

            png_bytes = cairosvg.svg2png(url=str(logo_path), output_width=64, output_height=64)
            return Image_module.open(BytesIO(png_bytes)).convert("RGBA")
        except Exception:
            pass

    image = Image_module.new("RGBA", (64, 64), (18, 49, 74, 255))
    draw = ImageDraw_module.Draw(image)
    draw.rounded_rectangle((6, 6, 58, 58), radius=16, fill=(68, 224, 199, 255))
    draw.rectangle((20, 18, 44, 24), fill=(18, 49, 74, 255))
    draw.rectangle((20, 30, 36, 36), fill=(18, 49, 74, 255))
    draw.rectangle((20, 42, 40, 48), fill=(18, 49, 74, 255))
    return image


def _remote_frontend_is_active(base_url: str) -> bool:
    return bool(_fetch_remote_session_snapshot(base_url).get("active"))


def _fetch_remote_session_snapshot(base_url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/runtime/frontend-session", timeout=1.5) as response:
            payload = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {"active": False, "sessionCount": 0}
    try:
        data = json.loads(payload)
    except Exception:
        return {"active": '"active": true' in payload.lower(), "sessionCount": 0}
    if isinstance(data, dict):
        return data
    return {"active": False, "sessionCount": 0}


def _request_remote_shutdown(base_url: str) -> bool:
    try:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/runtime/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2.0):
            return True
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _is_url_alive(base_url: str) -> bool:
    if not base_url:
        return False
    parsed = urllib.parse.urlparse(base_url)
    if not parsed.hostname or not parsed.port:
        return False
    return _is_port_open(parsed.hostname, parsed.port)


def _load_pystray():
    import pystray

    return pystray


def _load_pillow():
    from PIL import Image, ImageDraw

    return Image, ImageDraw


if __name__ == "__main__":
    main()
