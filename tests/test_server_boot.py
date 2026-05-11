from __future__ import annotations

import unittest
from unittest.mock import patch

from src import server_boot


class ServerBootTests(unittest.TestCase):
    def test_resolve_uvicorn_log_config_uses_default_when_console_streams_exist(self) -> None:
        with patch("src.server_boot._has_console_streams", return_value=True):
            self.assertIs(server_boot._resolve_uvicorn_log_config(), server_boot.uvicorn.config.LOGGING_CONFIG)

    def test_resolve_uvicorn_log_config_is_disabled_without_console_streams(self) -> None:
        with patch("src.server_boot._has_console_streams", return_value=False):
            self.assertIsNone(server_boot._resolve_uvicorn_log_config())

    def test_is_usable_stream_rejects_none(self) -> None:
        self.assertFalse(server_boot._is_usable_stream(None))


if __name__ == "__main__":
    unittest.main()
