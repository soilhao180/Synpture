from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src import diagnostics


class DiagnosticsRuntimeResourcesTests(unittest.TestCase):
    def test_browser_runtime_uses_effective_runtime_resource_paths(self) -> None:
        with (
            patch.object(
                diagnostics,
                "effective_runtime_resource_paths",
                return_value={
                    "node": Path("C:/runtime/node.exe"),
                    "node_modules": Path("C:/runtime/node_modules"),
                    "chromium": Path("C:/runtime/chrome.exe"),
                },
            ),
            patch.object(diagnostics.Path, "exists", autospec=True) as exists,
        ):
            exists.side_effect = lambda path: str(path).replace("\\", "/") in {
                "C:/runtime/node.exe",
                "C:/runtime/node_modules/playwright",
                "C:/runtime/chrome.exe",
            }
            item = diagnostics.check_browser_runtime()

        self.assertEqual(item.status, "ok")


if __name__ == "__main__":
    unittest.main()
