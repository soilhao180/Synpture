from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.diagnostics import DiagnosticItem
from src.models import TestResult
from src.presentation import web_app
import src.runtime_resources as runtime_resources
from src.transcription_runtime import TranscriptionCapability
from src.utils import write_json


class WebAppApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output_root = Path("output") / "workspace_web_app_api"
        shutil.rmtree(self.output_root, ignore_errors=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.env_path = self.output_root / ".env"
        self.env_path.write_text("", encoding="utf-8")
        self.original_output_dir = os.environ.get("OUTPUT_DIR")
        self.original_summary_model = os.environ.get("SUMMARY_API_MODEL")
        self.original_summary_api_key = os.environ.get("SUMMARY_API_KEY")
        os.environ["OUTPUT_DIR"] = str(self.output_root.resolve())
        os.environ["SUMMARY_API_MODEL"] = "gpt-5.4"
        os.environ["SUMMARY_API_KEY"] = "sk-test"

    def tearDown(self) -> None:
        shutil.rmtree(self.output_root, ignore_errors=True)
        _restore_env("OUTPUT_DIR", self.original_output_dir)
        _restore_env("SUMMARY_API_MODEL", self.original_summary_model)
        _restore_env("SUMMARY_API_KEY", self.original_summary_api_key)

    def test_bootstrap_runs_and_download_routes(self) -> None:
        _write_run(
            self.output_root / "run_20260501_090000",
            entry_type="share_link",
            title="https://example.com/demo",
            updated_at="2026-05-01 09:00:00",
            with_first_pass=True,
            with_template=True,
        )
        runtime_data_patch = patch("src.runtime_paths.get_user_data_root", return_value=self.output_root / "runtime_data")
        runtime_data_patch.start()
        self.addCleanup(runtime_data_patch.stop)

        with patch.object(web_app, "ENV_PATH", self.env_path):
            client = TestClient(web_app.create_web_app())

        bootstrap = client.get("/api/bootstrap")
        self.assertEqual(bootstrap.status_code, 200)
        payload = bootstrap.json()
        self.assertEqual(payload["defaultToolView"], "share_link")
        self.assertEqual(payload["runs"][0]["id"], "run_20260501_090000")
        self.assertIn("browserRuntime", payload)
        self.assertIn("runtimeResources", payload)
        self.assertEqual(
            {item["id"] for item in payload["runtimeResources"]["resources"]},
            {"model", "browser_runtime", "transcription_runtime"},
        )

        run_list = client.get("/api/runs")
        self.assertEqual(run_list.status_code, 200)
        self.assertEqual(run_list.json()[0]["recoveryState"], "completed")

        detail = client.get("/api/runs/run_20260501_090000")
        self.assertEqual(detail.status_code, 200)
        detail_payload = detail.json()
        self.assertEqual(detail_payload["recoveryState"], "completed")
        self.assertIn("transcriptSection", detail_payload)
        self.assertIn("firstPass", detail_payload)
        self.assertIn("skillOptions", detail_payload)
        self.assertIn("skillResults", detail_payload)
        self.assertEqual(detail_payload["nextStep"]["title"], "当前状态")

        download = client.get("/api/runs/run_20260501_090000/download/first_pass.json")
        self.assertEqual(download.status_code, 200)

        resources = client.get("/api/runtime/resources")
        self.assertEqual(resources.status_code, 200)
        model = next(item for item in resources.json()["resources"] if item["id"] == "model")
        self.assertFalse(model["ready"])
        self.assertTrue(model["sha256Configured"])

        blocked_download = client.post("/api/runtime/resources/model/download")
        self.assertIn(blocked_download.status_code, {200, 400})

        missing_resource = client.get("/api/runtime/resources/unknown/status")
        self.assertEqual(missing_resource.status_code, 404)

    def test_settings_and_health_routes(self) -> None:
        with (
            patch.object(web_app, "ENV_PATH", self.env_path),
            patch("src.runtime_paths.get_user_data_root", return_value=self.output_root / "runtime_data"),
        ):
            client = TestClient(web_app.create_web_app())

        settings_response = client.get("/api/settings")
        self.assertEqual(settings_response.status_code, 200)
        self.assertEqual(settings_response.json()["summaryApiModel"], "gpt-5.4")

        saved = client.post(
            "/api/settings",
            json={
                "summaryApiBaseUrl": "https://api.example.com/v1",
                "summaryApiKey": "sk-live",
                "summaryApiModel": "gpt-5.5",
                "transcribeBackend": "local",
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["summaryApiModel"], "gpt-5.5")
        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("SUMMARY_API_MODEL=gpt-5.5", env_content)
        self.assertIn("TRANSCRIBE_BACKEND=local", env_content)

        health_idle = client.get("/api/health")
        self.assertEqual(health_idle.status_code, 200)
        self.assertFalse(health_idle.json()["hasRun"])

        health_run = client.post("/api/health/run")
        self.assertEqual(health_run.status_code, 200)
        self.assertTrue(health_run.json()["hasRun"])
        self.assertIn("checks", health_run.json())

    def test_settings_actions_do_not_500_when_api_key_missing(self) -> None:
        original_summary_api_key = os.environ.get("SUMMARY_API_KEY")
        os.environ.pop("SUMMARY_API_KEY", None)
        self.env_path.write_text("SUMMARY_API_MODEL=gpt-5.4\n", encoding="utf-8")

        try:
            with patch.object(web_app, "ENV_PATH", self.env_path):
                client = TestClient(web_app.create_web_app())

            connection = client.post("/api/settings/test-connection")
            self.assertEqual(connection.status_code, 200)
            self.assertFalse(connection.json()["ok"])
            self.assertIn("SUMMARY_API_KEY", connection.json()["message"])

            models = client.get("/api/settings/models")
            self.assertEqual(models.status_code, 200)
            self.assertFalse(models.json()["ok"])
            self.assertIn("SUMMARY_API_KEY", models.json()["message"])

            test_model = client.post("/api/settings/test-model", json={"modelName": "gpt-5.4"})
            self.assertEqual(test_model.status_code, 200)
            self.assertFalse(test_model.json()["ok"])
            self.assertIn("SUMMARY_API_KEY", test_model.json()["message"])
        finally:
            _restore_env("SUMMARY_API_KEY", original_summary_api_key)

    def test_settings_actions_can_use_unsaved_form_values(self) -> None:
        original_summary_api_key = os.environ.get("SUMMARY_API_KEY")
        os.environ.pop("SUMMARY_API_KEY", None)
        self.env_path.write_text("SUMMARY_API_MODEL=gpt-5.4\n", encoding="utf-8")

        captured = []

        def fake_test_connection(settings):
            captured.append((settings.summary_api_base_url, settings.summary_api_key, settings.summary_api_model))
            return TestResult(ok=True, kind="summary_connection", message="ok")

        try:
            with patch.object(web_app, "ENV_PATH", self.env_path):
                with patch.object(web_app.SummaryService, "test_summary_connection", side_effect=fake_test_connection):
                    client = TestClient(web_app.create_web_app())
                    response = client.post(
                        "/api/settings/test-connection",
                        json={
                            "summaryApiBaseUrl": "https://api.example.com/v1",
                            "summaryApiKey": "sk-unsaved",
                            "summaryApiModel": "gpt-test",
                            "transcribeBackend": "auto",
                            "keepExistingApiKey": False,
                        },
                    )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ok"])
            self.assertEqual(captured, [("https://api.example.com/v1", "sk-unsaved", "gpt-test")])
            self.assertNotIn("sk-unsaved", self.env_path.read_text(encoding="utf-8"))
        finally:
            _restore_env("SUMMARY_API_KEY", original_summary_api_key)

    def test_transcription_capability_routes_and_preference_writeback(self) -> None:
        capability_before = TranscriptionCapability(
            gpu_status="recoverable",
            gpu_reason="已检测到 NVIDIA 显卡，但 GPU 运行环境不完整：缺少 CUDA 运行时。",
            gpu_recoverable=True,
            cpu_fallback_available=True,
            preferred_backend="gpu",
            allow_cpu_fallback=False,
            decision_required=True,
            nvidia_detected=True,
            cpu_reason="CPU 兼容模式可用：build-core whisper-cli.exe",
            gpu_details=["检测到显卡：NVIDIA RTX 4060"],
        )
        capability_after = TranscriptionCapability(
            gpu_status="recoverable",
            gpu_reason="已检测到 NVIDIA 显卡，但 GPU 运行环境不完整：缺少 CUDA 运行时。",
            gpu_recoverable=True,
            cpu_fallback_available=True,
            preferred_backend="cpu",
            allow_cpu_fallback=True,
            decision_required=False,
            nvidia_detected=True,
            cpu_reason="CPU 兼容模式可用：build-core whisper-cli.exe",
            gpu_details=["检测到显卡：NVIDIA RTX 4060"],
        )

        with patch.object(web_app, "ENV_PATH", self.env_path):
            with (
                patch.object(web_app, "probe_transcription_capability", side_effect=[capability_before, capability_after, capability_after]),
                patch.object(web_app, "save_transcription_runtime_state"),
            ):
                client = TestClient(web_app.create_web_app())
                bootstrap = client.get("/api/bootstrap")
                self.assertEqual(bootstrap.status_code, 200)
                self.assertEqual(bootstrap.json()["transcription"]["gpuStatus"], "recoverable")

                saved = client.post("/api/runtime/transcription-preference", json={"allowCpuFallback": True})
                self.assertEqual(saved.status_code, 200)
                self.assertTrue(saved.json()["allowCpuFallback"])
                self.assertEqual(saved.json()["preferredBackend"], "cpu")

                current = client.get("/api/runtime/transcription-capability")
                self.assertEqual(current.status_code, 200)
                self.assertTrue(current.json()["cpuFallbackAvailable"])

    def test_runtime_resource_upload_installs_local_file(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="synpture_resource_upload_"))
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        manifest = temp_dir / "runtime_resources.json"
        manifest.write_text(
            """
            {
              "resources": [
                {
                  "id": "sample",
                  "title": "Sample Runtime",
                  "description": "sample",
                  "url": "",
                  "sha256": "",
                  "archive": false,
                  "target": "models/sample.bin",
                  "requiredFor": ["test"]
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        with (
            patch.object(web_app, "ENV_PATH", self.env_path),
            patch.object(runtime_resources, "MANIFEST_PATH", manifest),
            patch("src.runtime_paths.get_user_data_root", return_value=temp_dir / "data"),
        ):
            client = TestClient(web_app.create_web_app())
            upload = client.post(
                "/api/runtime/resources/sample/upload",
                files={"file": ("sample.bin", b"runtime", "application/octet-stream")},
            )

        self.assertEqual(upload.status_code, 200)
        self.assertTrue(upload.json()["ready"])
        self.assertTrue((temp_dir / "data" / "models" / "sample.bin").exists())

    def test_frontend_session_routes_track_open_heartbeat_and_close(self) -> None:
        with (
            patch.object(web_app, "ENV_PATH", self.env_path),
            patch("src.runtime_paths.get_user_data_root", return_value=self.output_root / "runtime_data"),
        ):
            client = TestClient(web_app.create_web_app())

        initial = client.get("/api/runtime/frontend-session")
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.json()["active"])

        opened = client.post(
            "/api/runtime/frontend-session/open",
            json={"clientId": "client-1", "page": "workspace"},
        )
        self.assertEqual(opened.status_code, 200)
        self.assertTrue(opened.json()["active"])
        self.assertEqual(opened.json()["sessionCount"], 1)

        heartbeat = client.post(
            "/api/runtime/frontend-session/heartbeat",
            json={"clientId": "client-1", "page": "run"},
        )
        self.assertEqual(heartbeat.status_code, 200)
        self.assertTrue(heartbeat.json()["active"])
        self.assertIn("run", heartbeat.json()["pages"])

        closed = client.post(
            "/api/runtime/frontend-session/close",
            json={"clientId": "client-1"},
        )
        self.assertEqual(closed.status_code, 200)
        self.assertFalse(closed.json()["active"])

    def test_runtime_shutdown_route_calls_handler(self) -> None:
        shutdown_calls: list[str] = []

        def shutdown_handler() -> None:
            shutdown_calls.append("called")

        with patch.object(web_app, "ENV_PATH", self.env_path):
            client = TestClient(web_app.create_web_app(shutdown_handler=shutdown_handler))

        response = client.post("/api/runtime/shutdown")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        deadline = time.time() + 1.0
        while time.time() < deadline and not shutdown_calls:
            time.sleep(0.01)
        self.assertEqual(shutdown_calls, ["called"])

    def test_save_settings_keeps_existing_api_key_when_requested(self) -> None:
        self.env_path.write_text("SUMMARY_API_KEY=sk-existing\nSUMMARY_API_MODEL=gpt-5.4\n", encoding="utf-8")
        os.environ["SUMMARY_API_KEY"] = "sk-existing"

        with (
            patch.object(web_app, "ENV_PATH", self.env_path),
            patch("src.runtime_paths.get_user_data_root", return_value=self.output_root / "runtime_data"),
        ):
            client = TestClient(web_app.create_web_app())

        saved = client.post(
            "/api/settings",
            json={
                "summaryApiBaseUrl": "https://api.example.com/v1",
                "summaryApiKey": "",
                "summaryApiModel": "gpt-5.5",
                "transcribeBackend": "local",
                "keepExistingApiKey": True,
            },
        )
        self.assertEqual(saved.status_code, 200)
        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("SUMMARY_API_KEY=sk-existing", env_content)

    def test_backend_creates_missing_env_from_example(self) -> None:
        missing_env = self.output_root / "missing.env"
        bundled_root = self.output_root / "bundle"
        bundled_root.mkdir(parents=True, exist_ok=True)
        (bundled_root / ".env.example").write_text(
            "SUMMARY_API_MODEL=gpt-5.4\nTRANSCRIBE_BACKEND=auto\n",
            encoding="utf-8",
        )

        with (
            patch.object(web_app, "ENV_PATH", missing_env),
            patch("src.runtime_paths.get_app_root", return_value=bundled_root),
            patch("src.runtime_paths.is_packaged", return_value=False),
        ):
            client = TestClient(web_app.create_web_app())

        self.assertTrue(missing_env.exists())
        created_content = missing_env.read_text(encoding="utf-8")
        self.assertIn("SUMMARY_API_MODEL=gpt-5.4", created_content)
        settings_response = client.get("/api/settings")
        self.assertEqual(settings_response.status_code, 200)

    def test_auth_routes_report_pending_open_and_live_status(self) -> None:
        with patch.object(web_app, "ENV_PATH", self.env_path):
            with (
                patch.object(web_app, "launch_managed_auth_browser"),
                patch.object(
                    web_app,
                    "inspect_managed_auth_profile",
                    return_value={"ok": True, "summary": "已授权", "details": ["关键 Cookie 已就绪"]},
                ),
            ):
                client = TestClient(web_app.create_web_app())
                opened = client.post("/api/auth/bilibili/open")
                self.assertEqual(opened.status_code, 200)
                self.assertFalse(opened.json()["available"])
                self.assertEqual(opened.json()["statusLabel"], "等待检查")

                status = client.get("/api/auth/bilibili/status")
                self.assertEqual(status.status_code, 200)
                self.assertTrue(status.json()["available"])
                self.assertEqual(status.json()["statusLabel"], "可用")

    def test_auth_open_returns_clear_error_when_browser_runtime_missing(self) -> None:
        with patch.object(web_app, "ENV_PATH", self.env_path):
            with patch.object(
                web_app,
                "check_browser_runtime",
                return_value=DiagnosticItem(
                    name="授权浏览器运行时",
                    status="warn",
                    detail="未检测到可用的 Chrome/Chromium。",
                    recommendation="请安装 Google Chrome、内置 Chromium，或补齐授权浏览器运行时。",
                ),
            ):
                client = TestClient(web_app.create_web_app())
                response = client.post("/api/auth/bilibili/open")
                self.assertEqual(response.status_code, 503)
                self.assertIn("Chrome/Chromium", response.json()["detail"])

    def test_task_creation_and_status_routes(self) -> None:
        _write_run(
            self.output_root / "run_20260501_120000",
            entry_type="pasted_text",
            title="notes",
            updated_at="2026-05-01 12:00:00",
            with_first_pass=True,
        )

        task_payload = {
            "taskId": "task-123",
            "state": "succeeded",
            "phase": "artifact_write",
            "phaseLabel": "已完成",
            "progressPercent": 100,
            "message": "任务已完成。",
            "runId": "run_20260501_120000",
            "runDir": str((self.output_root / "run_20260501_120000").resolve()),
            "errorCode": None,
            "errorDetail": None,
            "result": {"runId": "run_20260501_120000"},
            "createdAt": "2026-05-01 12:00:00",
            "updatedAt": "2026-05-01 12:01:00",
            "history": [
                {
                    "label": "任务创建",
                    "detail": "任务已创建。",
                    "updatedAt": "2026-05-01 12:00:00",
                    "progressPercent": 0,
                },
                {
                    "label": "第一稿生成",
                    "detail": "正在整理第一稿。",
                    "updatedAt": "2026-05-01 12:00:30",
                    "progressPercent": 72,
                },
                {
                    "label": "已完成",
                    "detail": "任务已完成。",
                    "updatedAt": "2026-05-01 12:01:00",
                    "progressPercent": 100,
                },
            ],
        }

        cancel_payload = {
            "taskId": "task-123",
            "state": "running",
            "phase": "template_pass",
            "phaseLabel": "中止中",
            "progressPercent": 48,
            "message": "已发送中止请求，等待当前步骤结束。",
            "runId": "run_20260501_120000",
            "runDir": str((self.output_root / "run_20260501_120000").resolve()),
            "errorCode": None,
            "errorDetail": None,
            "result": None,
            "createdAt": "2026-05-01 12:00:00",
            "updatedAt": "2026-05-01 12:00:40",
            "history": [
                {
                    "label": "任务创建",
                    "detail": "任务已创建。",
                    "updatedAt": "2026-05-01 12:00:00",
                    "progressPercent": 0,
                },
                {
                    "label": "中止中",
                    "detail": "已发送中止请求，等待当前步骤结束。",
                    "updatedAt": "2026-05-01 12:00:40",
                    "progressPercent": 48,
                },
            ],
        }

        with patch.object(web_app, "ENV_PATH", self.env_path):
            with (
                patch.object(web_app.WorkspaceBackend, "create_share_link_task", return_value="task-123"),
                patch.object(web_app.WorkspaceBackend, "create_local_media_task", return_value="task-123"),
                patch.object(web_app.WorkspaceBackend, "create_text_file_task", return_value="task-123"),
                patch.object(web_app.WorkspaceBackend, "create_pasted_text_task", return_value="task-123"),
                patch.object(web_app.WorkspaceBackend, "create_recovery_upload_task", return_value="task-123"),
                patch.object(web_app.WorkspaceBackend, "resume_first_pass_task", return_value="task-123"),
                patch.object(web_app.WorkspaceBackend, "resume_templates_task", return_value="task-123"),
                patch.object(web_app.WorkspaceBackend, "get_task_payload", return_value=task_payload),
                patch.object(web_app.WorkspaceBackend, "cancel_task", return_value=cancel_payload),
            ):
                client = TestClient(web_app.create_web_app())

                self.assertEqual(
                    client.post("/api/tasks/share-link", json={"shareUrl": "https://example.com/demo"}).json()["taskId"],
                    "task-123",
                )
                self.assertEqual(
                    client.post(
                        "/api/tasks/local-media",
                        files={"file": ("demo.mp4", b"video", "video/mp4")},
                    ).json()["taskId"],
                    "task-123",
                )
                self.assertEqual(
                    client.post(
                        "/api/tasks/text-file",
                        files={"file": ("demo.txt", b"hello", "text/plain")},
                    ).json()["taskId"],
                    "task-123",
                )
                self.assertEqual(
                    client.post("/api/tasks/pasted-text", json={"text": "hello world"}).json()["taskId"],
                    "task-123",
                )
                self.assertEqual(
                    client.post(
                        "/api/tasks/recovery/uploaded-dir",
                        files=[("files", ("project/demo.txt", b"hello", "text/plain"))],
                    ).json()["taskId"],
                    "task-123",
                )
                self.assertEqual(
                    client.post("/api/runs/run_20260501_120000/resume-first-pass", json={"modelName": "gpt-5.4"}).json()["taskId"],
                    "task-123",
                )
                self.assertEqual(
                    client.post(
                        "/api/runs/run_20260501_120000/resume-templates",
                        json={"templateId": "minimal-summary", "summaryModel": "gpt-5.4"},
                    ).json()["taskId"],
                    "task-123",
                )
                self.assertEqual(
                    client.post(
                        "/api/runs/run_20260501_120000/templates/minimal-summary",
                        json={"templateId": "minimal-summary", "summaryModel": "gpt-5.4"},
                    ).json()["taskId"],
                    "task-123",
                )
                status = client.get("/api/tasks/task-123/status")
                self.assertEqual(status.status_code, 200)
                self.assertEqual(status.json()["runId"], "run_20260501_120000")
                self.assertEqual(len(status.json()["history"]), 3)

                cancelled = client.post("/api/tasks/task-123/cancel")
                self.assertEqual(cancelled.status_code, 200)
                self.assertEqual(cancelled.json()["phaseLabel"], "中止中")


def _write_run(
    run_dir: Path,
    *,
    entry_type: str,
    title: str,
    updated_at: str,
    with_first_pass: bool = False,
    with_template: bool = False,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "job.json",
        {
            "entry_type": entry_type,
            "source_label": title,
            "state": "succeeded" if with_first_pass else "running",
            "progress_percent": 100 if with_template else 92 if with_first_pass else 68,
            "updated_at": updated_at,
        },
    )
    write_json(
        run_dir / "input_source.json",
        {
            "source_id": "source",
            "entry_type": entry_type,
            "content_type": "plain_text",
            "display_name": title,
            "original_filename": None,
            "mime_type": None,
            "local_path": None,
            "text_content": None,
            "url": title if entry_type == "share_link" else None,
            "metadata": {},
        },
    )
    (run_dir / "transcript.txt").write_text("hello world", encoding="utf-8")
    write_json(run_dir / "segments.json", {"segments": []})
    write_json(run_dir / "chunks.json", {"chunks": []})
    if with_first_pass:
        write_json(
            run_dir / "first_pass.json",
            {
                "provider": "test",
                "model": "test-model",
                "cleaned_transcript": "cleaned transcript",
                "headline_verdict": "usable",
                "value_rating": "high",
                "value_reason": "good",
                "high_value_points": ["point"],
                "objective_context": ["context"],
                "low_value_segments": [],
                "raw_transcript_reference": "raw transcript",
                "warning": None,
            },
        )
    if with_template:
        write_json(
            run_dir / "template_minimal-summary.json",
            {
                "template_id": "minimal-summary",
                "template_name": "Minimal Summary",
                "provider": "test",
                "model": "test-model",
                "overview": "overview",
                "key_points": [],
                "section_summaries": [],
                "template_fields": {},
                "warning": None,
            },
        )


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
