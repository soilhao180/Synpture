from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import src.runtime_resources as runtime_resources
import src.runtime_paths as runtime_paths


class RuntimeResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="synpture_runtime_resources_"))
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))
        self.manifest_path = self.temp_dir / "runtime_resources.json"
        self.manifest_path.write_text(
            """
            {
              "resources": [
                {
                  "id": "browser_runtime",
                  "title": "Browser Runtime",
                  "description": "browser",
                  "url": "",
                  "sha256": "",
                  "archive": true,
                  "target": "third_party/browser_runtime",
                  "markers": [
                    "node/node.exe",
                    "node_runtime/node_modules/playwright/package.json",
                    "chromium/chrome.exe"
                  ],
                  "requiredFor": ["share_auth"]
                },
                {
                  "id": "transcription_runtime",
                  "title": "Transcription Runtime",
                  "description": "transcription",
                  "url": "",
                  "sha256": "",
                  "archive": true,
                  "target": "third_party/transcription_runtime",
                  "markers": [
                    "ffmpeg/bin/ffmpeg.exe",
                    "ffmpeg/bin/ffprobe.exe",
                    "whisper.cpp/build-cuda/bin/whisper-cli.exe",
                    "whisper.cpp/build-core/bin/whisper-cli.exe"
                  ],
                  "requiredFor": ["transcription"]
                }
              ]
            }
            """,
            encoding="utf-8",
        )

    def test_dev_source_layout_marks_legacy_runtime_resources_ready(self) -> None:
        app_root = self.temp_dir / "app"
        user_data_root = app_root
        for relative_path in (
            "third_party/node/node.exe",
            "third_party/node_runtime/node_modules/playwright/package.json",
            "third_party/chromium/chrome.exe",
            "third_party/ffmpeg/bin/ffmpeg.exe",
            "third_party/ffmpeg/bin/ffprobe.exe",
            "third_party/whisper.cpp/build-cuda/bin/whisper-cli.exe",
            "third_party/whisper.cpp/build-core/bin/whisper-cli.exe",
        ):
            path = app_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("runtime", encoding="utf-8")

        with (
            patch.object(runtime_resources, "MANIFEST_PATH", self.manifest_path),
            patch.object(runtime_resources, "is_packaged", return_value=False),
            patch.object(runtime_resources, "get_app_root", return_value=app_root),
            patch.object(runtime_resources, "get_user_data_root", return_value=user_data_root),
            patch.object(runtime_resources, "user_data_path", side_effect=lambda *parts: user_data_root.joinpath(*parts)),
            patch.object(runtime_paths, "get_user_data_root", return_value=user_data_root),
        ):
            resources = {item["id"]: item for item in runtime_resources.serialize_runtime_resources()}

        self.assertTrue(resources["browser_runtime"]["ready"])
        self.assertEqual(resources["browser_runtime"]["targetPath"], str(app_root / "third_party"))
        self.assertTrue(resources["transcription_runtime"]["ready"])
        self.assertEqual(resources["transcription_runtime"]["targetPath"], str(app_root / "third_party"))

    def test_packaged_layout_does_not_use_dev_source_fallback(self) -> None:
        app_root = self.temp_dir / "app"
        user_data_root = self.temp_dir / "data"
        path = app_root / "third_party" / "ffmpeg" / "bin" / "ffmpeg.exe"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("runtime", encoding="utf-8")

        with (
            patch.object(runtime_resources, "MANIFEST_PATH", self.manifest_path),
            patch.object(runtime_resources, "is_packaged", return_value=True),
            patch.object(runtime_resources, "get_app_root", return_value=app_root),
            patch.object(runtime_resources, "get_user_data_root", return_value=user_data_root),
            patch.object(runtime_resources, "user_data_path", side_effect=lambda *parts: user_data_root.joinpath(*parts)),
            patch.object(runtime_paths, "get_user_data_root", return_value=user_data_root),
        ):
            status = runtime_resources.get_runtime_resource_status("transcription_runtime")

        self.assertFalse(status["ready"])
        self.assertEqual(status["targetPath"], str(user_data_root / "third_party" / "transcription_runtime"))


if __name__ == "__main__":
    unittest.main()
