from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import synpture_launcher


class SynptureLauncherTests(unittest.TestCase):
    def test_find_running_server_port_returns_existing_port(self) -> None:
        with patch("synpture_launcher._is_port_open", side_effect=lambda host, port: port == 8002):
            self.assertEqual(synpture_launcher._find_running_server_port("127.0.0.1", 8000, max_attempts=5), 8002)

    def test_find_running_server_port_returns_none_when_absent(self) -> None:
        with patch("synpture_launcher._is_port_open", return_value=False):
            self.assertIsNone(synpture_launcher._find_running_server_port("127.0.0.1", 8000, max_attempts=3))

    def test_should_open_browser_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNPTURE_NO_BROWSER", None)
            self.assertTrue(synpture_launcher._should_open_browser())

    def test_should_not_open_browser_when_disabled(self) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"SYNPTURE_NO_BROWSER": value}, clear=False):
                    self.assertFalse(synpture_launcher._should_open_browser())

    def test_build_session_status_label(self) -> None:
        self.assertEqual(
            synpture_launcher._build_session_status_label(
                synpture_launcher.FrontendLifecycleState(
                    state=synpture_launcher.STATE_ACTIVE,
                    active_count=1,
                )
            ),
            "前端已打开 (1)",
        )
        self.assertEqual(
            synpture_launcher._build_session_status_label(
                synpture_launcher.FrontendLifecycleState(state=synpture_launcher.STATE_PENDING_OPEN)
            ),
            "正在等待前端连接",
        )
        self.assertEqual(
            synpture_launcher._build_session_status_label(
                synpture_launcher.FrontendLifecycleState(state=synpture_launcher.STATE_INACTIVE)
            ),
            "前端未打开",
        )

    def test_open_browser_if_needed_skips_when_active(self) -> None:
        launcher = synpture_launcher.SynptureLauncherApp()
        launcher.url = "http://127.0.0.1:8000/"
        launcher.frontend_sessions.open("client-1", page="workspace")
        with patch("synpture_launcher.webbrowser.open") as mocked_open:
            self.assertFalse(launcher.open_browser_if_needed())
        mocked_open.assert_not_called()

    def test_open_browser_if_needed_forces_open_even_when_active(self) -> None:
        launcher = synpture_launcher.SynptureLauncherApp()
        launcher.url = "http://127.0.0.1:8000/"
        launcher.frontend_sessions.open("client-1", page="workspace")
        with patch("synpture_launcher.webbrowser.open") as mocked_open:
            self.assertTrue(launcher.open_browser_if_needed(force=True))
        mocked_open.assert_called_once_with("http://127.0.0.1:8000/")
        self.assertEqual(launcher._lifecycle.state, synpture_launcher.STATE_PENDING_OPEN)

    def test_force_open_browser_always_opens(self) -> None:
        launcher = synpture_launcher.SynptureLauncherApp()
        launcher.url = "http://127.0.0.1:8000/"
        launcher.frontend_sessions.open("client-1", page="workspace")
        with patch("synpture_launcher.webbrowser.open") as mocked_open:
            self.assertTrue(launcher.force_open_browser())
        mocked_open.assert_called_once_with("http://127.0.0.1:8000/")

    def test_pending_open_blocks_normal_reopen_until_timeout(self) -> None:
        launcher = synpture_launcher.SynptureLauncherApp()
        launcher.url = "http://127.0.0.1:8000/"
        with patch("synpture_launcher.webbrowser.open"):
            self.assertTrue(launcher.open_browser_if_needed())
        self.assertEqual(launcher._normalized_frontend_state().state, synpture_launcher.STATE_PENDING_OPEN)
        with patch("synpture_launcher.webbrowser.open") as mocked_open:
            self.assertFalse(launcher.open_browser_if_needed())
        mocked_open.assert_not_called()

    def test_pending_open_expires_to_inactive(self) -> None:
        launcher = synpture_launcher.SynptureLauncherApp()
        launcher.url = "http://127.0.0.1:8000/"
        with patch("synpture_launcher.webbrowser.open"):
            self.assertTrue(launcher.open_browser_if_needed())
        launcher._lifecycle.pending_until = 0.0
        self.assertEqual(launcher._normalized_frontend_state().state, synpture_launcher.STATE_INACTIVE)

    def test_open_heartbeat_transitions_pending_to_active(self) -> None:
        launcher = synpture_launcher.SynptureLauncherApp()
        launcher.url = "http://127.0.0.1:8000/"
        with patch("synpture_launcher.webbrowser.open"):
            self.assertTrue(launcher.open_browser_if_needed())
        launcher.frontend_sessions.open("client-1", page="workspace")
        state = launcher._normalized_frontend_state()
        self.assertEqual(state.state, synpture_launcher.STATE_ACTIVE)
        self.assertEqual(state.active_count, 1)

    def test_close_transitions_active_to_inactive(self) -> None:
        launcher = synpture_launcher.SynptureLauncherApp()
        launcher.url = "http://127.0.0.1:8000/"
        launcher.frontend_sessions.open("client-1", page="workspace")
        self.assertEqual(launcher._normalized_frontend_state().state, synpture_launcher.STATE_ACTIVE)
        launcher.frontend_sessions.close("client-1")
        self.assertEqual(launcher._normalized_frontend_state().state, synpture_launcher.STATE_INACTIVE)

    def test_attached_mode_reads_remote_state(self) -> None:
        launcher = synpture_launcher.SynptureLauncherApp()
        launcher.url = "http://127.0.0.1:8000/"
        launcher._attached_to_existing_server = True
        with patch(
            "synpture_launcher._fetch_remote_session_snapshot",
            return_value={"active": True, "sessionCount": 1},
        ):
            state = launcher._normalized_frontend_state()
        self.assertEqual(state.state, synpture_launcher.STATE_ACTIVE)
        self.assertEqual(state.active_count, 1)

    def test_shutdown_requests_remote_shutdown_when_attached(self) -> None:
        launcher = synpture_launcher.SynptureLauncherApp()
        launcher.url = "http://127.0.0.1:8000/"
        launcher._attached_to_existing_server = True
        with patch("synpture_launcher._request_remote_shutdown", return_value=True) as mocked_shutdown:
            launcher.shutdown()
        mocked_shutdown.assert_called_once_with("http://127.0.0.1:8000/")


if __name__ == "__main__":
    unittest.main()
