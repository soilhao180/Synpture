from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import Settings
from src import transcription_runtime


class TranscriptionRuntimeCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="synpture_transcription_runtime_"))
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_probe_uses_effective_runtime_resource_paths_over_stale_settings_paths(self) -> None:
        model = self.temp_dir / "models" / "ggml-large-v3-turbo-q5_0.bin"
        ffmpeg = self.temp_dir / "third_party" / "transcription_runtime" / "ffmpeg" / "bin" / "ffmpeg.exe"
        gpu = self.temp_dir / "third_party" / "transcription_runtime" / "whisper.cpp" / "build-cuda" / "bin" / "whisper-cli.exe"
        cpu = self.temp_dir / "third_party" / "transcription_runtime" / "whisper.cpp" / "build-core" / "bin" / "whisper-cli.exe"
        for path in (model, ffmpeg, gpu, cpu):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stub", encoding="utf-8")

        settings = Settings(
            whisper_cpp_model_path=self.temp_dir / "stale" / "missing-model.bin",
            ffmpeg_bin=str(self.temp_dir / "stale" / "ffmpeg.exe"),
            whisper_cpp_bin=str(self.temp_dir / "stale" / "gpu.exe"),
            whisper_cpp_cpu_bin=str(self.temp_dir / "stale" / "cpu.exe"),
        )

        with (
            patch.object(
                transcription_runtime,
                "effective_runtime_resource_paths",
                return_value={
                    "model": model,
                    "ffmpeg": ffmpeg,
                    "whisper_gpu": gpu,
                    "whisper_cpu": cpu,
                },
            ),
            patch.object(transcription_runtime, "_detect_nvidia_hardware", return_value=(True, ["NVIDIA RTX"])),
            patch.object(transcription_runtime, "_probe_whisper_binary", return_value=(True, "ok")),
            patch.object(transcription_runtime, "_probe_nvidia_runtime", return_value=(True, "NVIDIA RTX, driver")),
            patch.object(transcription_runtime, "get_windows_debug_crt_dependencies", return_value=[]),
            patch.object(transcription_runtime, "load_transcription_runtime_state", return_value=transcription_runtime.TranscriptionRuntimeState()),
        ):
            capability = transcription_runtime.probe_transcription_capability(settings)

        self.assertEqual(capability.gpu_status, "ready")
        self.assertNotIn("missing-model.bin", capability.gpu_reason)


if __name__ == "__main__":
    unittest.main()
