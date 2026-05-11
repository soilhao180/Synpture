from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import runtime_paths


class RuntimePathsPackagedLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="synpture_packaged_layout_"))
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_bundled_path_falls_back_to_install_root_for_top_level_runtime_tools(self) -> None:
        install_root = self.temp_dir / "install"
        bundle_root = install_root / "_internal"
        tool_path = install_root / "third_party" / "ffmpeg" / "bin" / "ffmpeg.exe"
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_path.write_text("stub", encoding="utf-8")

        with (
            patch("src.runtime_paths.is_packaged", return_value=True),
            patch("src.runtime_paths.get_app_root", return_value=install_root),
            patch("src.runtime_paths.get_bundle_root", return_value=bundle_root),
        ):
            self.assertEqual(runtime_paths.bundled_path("third_party", "ffmpeg", "bin", "ffmpeg.exe"), tool_path)

    def test_packaged_env_rewrites_missing_runtime_paths_to_user_runtime_resources(self) -> None:
        install_root = self.temp_dir / "install"
        bundle_root = install_root / "_internal"
        data_root = self.temp_dir / "data"
        bundle_root.mkdir(parents=True, exist_ok=True)
        data_root.mkdir(parents=True, exist_ok=True)
        (bundle_root / ".env.example").write_text("OUTPUT_DIR=output\nFFMPEG_BIN=\n", encoding="utf-8")

        ffmpeg_path = data_root / "third_party" / "transcription_runtime" / "ffmpeg" / "bin" / "ffmpeg.exe"
        ffmpeg_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_path.write_text("stub", encoding="utf-8")

        env_path = data_root / ".env"
        env_path.write_text(
            "OUTPUT_DIR=C:/custom/output\n"
            "FFMPEG_BIN=D:/Synpture/_internal/third_party/ffmpeg/bin/ffmpeg.exe\n",
            encoding="utf-8",
        )

        with (
            patch("src.runtime_paths.is_packaged", return_value=True),
            patch("src.runtime_paths.get_app_root", return_value=install_root),
            patch("src.runtime_paths.get_bundle_root", return_value=bundle_root),
            patch("src.runtime_paths.get_user_data_root", return_value=data_root),
        ):
            runtime_paths.ensure_runtime_env(env_path)

        content = env_path.read_text(encoding="utf-8")
        self.assertIn("OUTPUT_DIR=C:/custom/output", content)
        self.assertIn(f"FFMPEG_BIN={ffmpeg_path}", content)

    def test_packaged_env_uses_system_ffmpeg_when_runtime_resource_is_missing(self) -> None:
        install_root = self.temp_dir / "install"
        bundle_root = install_root / "_internal"
        data_root = self.temp_dir / "data"
        bundle_root.mkdir(parents=True, exist_ok=True)
        data_root.mkdir(parents=True, exist_ok=True)
        env_path = data_root / ".env"
        env_path.write_text("FFMPEG_BIN=C:/missing/ffmpeg.exe\nFFPROBE_BIN=C:/missing/ffprobe.exe\n", encoding="utf-8")

        with (
            patch("src.runtime_paths.is_packaged", return_value=True),
            patch("src.runtime_paths.get_app_root", return_value=install_root),
            patch("src.runtime_paths.get_bundle_root", return_value=bundle_root),
            patch("src.runtime_paths.get_user_data_root", return_value=data_root),
            patch("src.runtime_paths.shutil.which", side_effect=lambda command: f"C:/Windows/System32/{command}.exe"),
        ):
            runtime_paths.ensure_runtime_env(env_path)

        content = env_path.read_text(encoding="utf-8")
        self.assertIn("FFMPEG_BIN=ffmpeg", content)
        self.assertIn("FFPROBE_BIN=ffprobe", content)


if __name__ == "__main__":
    unittest.main()
