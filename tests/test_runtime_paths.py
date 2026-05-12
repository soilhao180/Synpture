from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import runtime_paths
from src.config import load_settings
from src.template_registry import list_template_definitions


class RuntimePathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="synpture_runtime_paths_"))
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_dev_mode_paths_stay_in_repo_root(self) -> None:
        repo_root = self.temp_dir / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)

        with (
            patch("src.runtime_paths.is_packaged", return_value=False),
            patch("src.runtime_paths.get_app_root", return_value=repo_root),
        ):
            self.assertEqual(runtime_paths.get_env_path(), repo_root / ".env")
            self.assertEqual(runtime_paths.get_default_output_dir(), repo_root / "output")
            self.assertEqual(runtime_paths.get_managed_auth_root(), repo_root / "output" / "managed_auth_profiles")

    def test_packaged_mode_creates_env_and_rewrites_runtime_defaults(self) -> None:
        app_root = self.temp_dir / "bundle"
        data_root = self.temp_dir / "user_data"
        app_root.mkdir(parents=True, exist_ok=True)
        data_root.mkdir(parents=True, exist_ok=True)
        (app_root / ".env.example").write_text(
            "OUTPUT_DIR=output\n"
            "WHISPER_CPP_BIN=\n"
            "WHISPER_CPP_MODEL_PATH=models/ggml-large-v3-turbo-q5_0.bin\n"
            "FFMPEG_BIN=\n"
            "FFPROBE_BIN=\n"
            "SHARE_LINK_NODE_BIN=\n"
            "SHARE_LINK_NODE_PATH=\n",
            encoding="utf-8",
        )

        with (
            patch("src.runtime_paths.is_packaged", return_value=True),
            patch("src.runtime_paths.get_app_root", return_value=app_root),
            patch("src.runtime_paths.get_user_data_root", return_value=data_root),
        ):
            env_path = runtime_paths.ensure_runtime_env()

        self.assertEqual(env_path, data_root / ".env")
        content = env_path.read_text(encoding="utf-8")
        self.assertIn(f"OUTPUT_DIR={data_root / 'output'}", content)
        self.assertIn(f"WHISPER_CPP_BIN={data_root / 'third_party' / 'transcription_runtime' / 'whisper.cpp' / 'build-cuda' / 'bin' / 'whisper-cli.exe'}", content)
        self.assertIn(f"WHISPER_CPP_CPU_BIN={data_root / 'third_party' / 'transcription_runtime' / 'whisper.cpp' / 'build-core' / 'bin' / 'whisper-cli.exe'}", content)
        self.assertIn(f"WHISPER_CPP_MODEL_PATH={data_root / 'models' / 'ggml-large-v3-turbo-q5_0.bin'}", content)
        self.assertRegex(
            content,
            rf"FFMPEG_BIN=({re.escape(str(data_root / 'third_party' / 'transcription_runtime' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'))}|ffmpeg)",
        )
        self.assertRegex(
            content,
            rf"SHARE_LINK_NODE_BIN=({re.escape(str(data_root / 'third_party' / 'browser_runtime' / 'node' / 'node.exe'))}|node)",
        )

    def test_packaged_mode_keeps_user_env_overrides_and_backfills_missing_values(self) -> None:
        app_root = self.temp_dir / "bundle"
        data_root = self.temp_dir / "user_data"
        app_root.mkdir(parents=True, exist_ok=True)
        data_root.mkdir(parents=True, exist_ok=True)
        env_path = data_root / ".env"
        env_path.write_text(
            "OUTPUT_DIR=C:/custom/output\n"
            "WHISPER_CPP_BIN=\n"
            "SUMMARY_API_MODEL=gpt-5.4\n",
            encoding="utf-8",
        )

        with (
            patch("src.runtime_paths.is_packaged", return_value=True),
            patch("src.runtime_paths.get_app_root", return_value=app_root),
            patch("src.runtime_paths.get_user_data_root", return_value=data_root),
        ):
            runtime_paths.ensure_runtime_env(env_path)

        content = env_path.read_text(encoding="utf-8")
        self.assertIn("OUTPUT_DIR=C:/custom/output", content)
        self.assertIn(f"WHISPER_CPP_BIN={data_root / 'third_party' / 'transcription_runtime' / 'whisper.cpp' / 'build-cuda' / 'bin' / 'whisper-cli.exe'}", content)
        self.assertIn(f"WHISPER_CPP_CPU_BIN={data_root / 'third_party' / 'transcription_runtime' / 'whisper.cpp' / 'build-core' / 'bin' / 'whisper-cli.exe'}", content)
        self.assertIn("SUMMARY_API_MODEL=gpt-5.4", content)

    def test_load_settings_uses_packaged_defaults_when_env_missing(self) -> None:
        app_root = self.temp_dir / "bundle"
        data_root = self.temp_dir / "user_data"
        app_root.mkdir(parents=True, exist_ok=True)
        data_root.mkdir(parents=True, exist_ok=True)
        (app_root / ".env.example").write_text("SUMMARY_API_MODEL=gpt-5.4\n", encoding="utf-8")
        original_env = {
            "OUTPUT_DIR": os.environ.get("OUTPUT_DIR"),
            "WHISPER_CPP_MODEL_PATH": os.environ.get("WHISPER_CPP_MODEL_PATH"),
        }
        os.environ.pop("OUTPUT_DIR", None)
        os.environ.pop("WHISPER_CPP_MODEL_PATH", None)

        try:
            with (
                patch("src.runtime_paths.is_packaged", return_value=True),
                patch("src.runtime_paths.get_app_root", return_value=app_root),
                patch("src.runtime_paths.get_user_data_root", return_value=data_root),
                patch("src.config.PROJECT_ROOT", app_root),
                patch("src.config.DEFAULT_OUTPUT_DIR", data_root / "output"),
            ):
                settings = load_settings()
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(settings.output_dir, data_root / "output")
        self.assertEqual(settings.whisper_cpp_model_path, data_root / "models" / "ggml-large-v3-turbo-q5_0.bin")
        self.assertEqual(settings.whisper_cpp_cpu_bin, str(data_root / "third_party" / "transcription_runtime" / "whisper.cpp" / "build-core" / "bin" / "whisper-cli.exe"))

    def test_template_registry_reads_from_bundled_templates_root(self) -> None:
        app_root = self.temp_dir / "bundle"
        template_dir = app_root / "templates" / "skills" / "sample-template"
        template_dir.mkdir(parents=True, exist_ok=True)
        (template_dir / "template.json").write_text(
            '{'
            '"id":"sample-template",'
            '"name":"Sample Template",'
            '"description":"demo",'
            '"input_fields":["input"],'
            '"output_fields":["output"],'
            '"prompt_instructions":"focus"'
            '}',
            encoding="utf-8",
        )

        with (
            patch("src.template_registry.TEMPLATE_ROOT", app_root / "templates" / "skills"),
            patch("src.template_registry.get_custom_skills_root", return_value=self.temp_dir / "empty_skills"),
        ):
            definitions = list_template_definitions()

        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].id, "sample-template")

    def test_detects_windows_debug_crt_dependencies_in_binary(self) -> None:
        binary_path = self.temp_dir / "whisper-cli.exe"
        binary_path.write_bytes(b"header...MSVCP140D.dll...VCRUNTIME140_1D.dll...tail")

        dependencies = runtime_paths.get_windows_debug_crt_dependencies(binary_path)

        self.assertEqual(dependencies, ("MSVCP140D.dll", "VCRUNTIME140_1D.dll"))


if __name__ == "__main__":
    unittest.main()
