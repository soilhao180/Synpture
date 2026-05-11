from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import threading
import time
from typing import Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.application import PipelineOrchestrator
from src.config import load_settings
from src.diagnostics import check_browser_runtime, overall_status, run_startup_checks
from src.domain.job import JobRequest, JobStatus
from src.infrastructure.artifact_store import LocalArtifactStore
from src.presentation.api_serializers import (
    RECOVERY_LABELS,
    build_download_items,
    serialize_diagnostic_item,
    serialize_health_payload,
    serialize_platform_status,
    serialize_run_list_item,
    serialize_run_workspace,
    serialize_settings,
    serialize_transcription_capability,
    serialize_template_catalog,
)
from src.presentation.config_io import save_env_settings
from src.presentation.task_registry import TaskRegistry
from src.runtime_paths import bundled_path, ensure_runtime_env, get_env_path
from src.runtime_resources import (
    get_runtime_resource_status,
    install_runtime_resource_file,
    serialize_runtime_resources,
    start_runtime_resource_download,
)
from src.services.summary_service import SummaryService
from src.share_link_ingest import (
    get_managed_auth_user_data_dir,
    inspect_managed_auth_profile,
    launch_managed_auth_browser,
)
from src.transcription_runtime import probe_transcription_capability, save_transcription_runtime_state


WORKSPACE_UI_ROOT = bundled_path("workspace-ui")
SHARED_ASSET_ROOT = bundled_path("assets")
ENV_PATH = get_env_path()
WORKSPACE_INDEX_PATH = WORKSPACE_UI_ROOT / "index.html"
WORKSPACE_APP_JS_PATH = WORKSPACE_UI_ROOT / "src" / "app.js"
WORKSPACE_STYLES_PATH = WORKSPACE_UI_ROOT / "src" / "styles.css"

DEFAULT_TOOL_VIEW = "share_link"
PLATFORM_LABELS = {
    "douyin": "抖音",
    "bilibili": "B站",
    "xiaohongshu": "小红书",
    "wechat_butterfly": "微信蝴蝶号",
}


class ShareLinkTaskRequest(BaseModel):
    shareUrl: str
    summaryModel: str | None = None
    transcribeBackend: str | None = None


class PastedTextTaskRequest(BaseModel):
    text: str
    summaryModel: str | None = None


class ResumeTemplatesRequest(BaseModel):
    templateId: str | None = None
    summaryModel: str | None = None


class SettingsSaveRequest(BaseModel):
    summaryApiBaseUrl: str = ""
    summaryApiKey: str = ""
    summaryApiModel: str = ""
    transcribeBackend: str = "auto"
    keepExistingApiKey: bool = False


class ModelTestRequest(BaseModel):
    modelName: str | None = None


class SettingsTestRequest(SettingsSaveRequest):
    modelName: str | None = None


class TranscriptionPreferenceRequest(BaseModel):
    allowCpuFallback: bool


class FrontendSessionRequest(BaseModel):
    clientId: str
    page: str | None = None


@dataclass
class InMemoryUpload:
    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


class WorkspaceBackend:
    def __init__(
        self,
        *,
        env_path: Path | None = None,
        frontend_sessions: "FrontendSessionTracker | None" = None,
    ) -> None:
        self.env_path = ensure_runtime_env(env_path or ENV_PATH)
        self.task_registry = TaskRegistry()
        self.health_items: list[Any] = []
        self.frontend_sessions = frontend_sessions or FrontendSessionTracker()
        self.reload()

    def reload(self) -> None:
        self.settings = load_settings(self.env_path)
        self.artifact_store = LocalArtifactStore(self.settings.output_dir)
        self.orchestrator = PipelineOrchestrator(self.settings, artifact_store=self.artifact_store)
        self.summary_service = SummaryService()

    def build_bootstrap_payload(self) -> dict[str, Any]:
        runs = self._list_run_items()
        return {
            "defaultToolView": DEFAULT_TOOL_VIEW,
            "toolViews": [
                {"id": "share_link", "label": "分享链接"},
                {"id": "local_media", "label": "本地媒体"},
                {"id": "text_input", "label": "文本输入"},
                {"id": "recovery", "label": "恢复项目"},
            ],
            "startPage": {
                "logoUrl": "/assets/icons/start-page-logo.svg",
                "enterButtonUrl": "/shared-assets/start-page/Frame-10.svg",
                "legacyButtonFallbackUrl": "/shared-assets/start-page/frame-8.png",
            },
            "settings": serialize_settings(self.settings),
            "browserRuntime": serialize_diagnostic_item(check_browser_runtime()),
            "transcription": self.get_transcription_capability_payload(),
            "runtimeResources": self.get_runtime_resources_payload(),
            "health": self.get_health_payload(),
            "platforms": self.get_platform_statuses(),
            "runs": [serialize_run_list_item(item) for item in runs],
            "resumeCandidate": self.find_resume_candidate(),
            "templates": serialize_template_catalog(self.summary_service.list_runtime_templates()),
        }

    def get_settings_payload(self) -> dict[str, Any]:
        return serialize_settings(self.settings)

    def get_transcription_capability_payload(self) -> dict[str, Any]:
        return serialize_transcription_capability(probe_transcription_capability(self.settings))

    def get_runtime_resources_payload(self) -> dict[str, Any]:
        return {"resources": serialize_runtime_resources()}

    def get_runtime_resource_status_payload(self, resource_id: str) -> dict[str, Any]:
        try:
            return get_runtime_resource_status(resource_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown runtime resource: {resource_id}") from None

    def start_runtime_resource_download_payload(self, resource_id: str) -> dict[str, Any]:
        try:
            payload = start_runtime_resource_download(resource_id)
            self.reload()
            return payload
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown runtime resource: {resource_id}") from None
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def install_runtime_resource_upload_payload(self, resource_id: str, file_name: str, file_bytes: bytes) -> dict[str, Any]:
        try:
            temp_dir = self.settings.output_dir / "_runtime_resource_uploads"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_path = temp_dir / (Path(file_name).name or f"{resource_id}.bin")
            temp_path.write_bytes(file_bytes)
            payload = install_runtime_resource_file(resource_id, temp_path)
            self.reload()
            return payload
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown runtime resource: {resource_id}") from None
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def save_transcription_preference_payload(self, payload: TranscriptionPreferenceRequest) -> dict[str, Any]:
        save_transcription_runtime_state(allow_cpu_fallback=payload.allowCpuFallback)
        return self.get_transcription_capability_payload()

    def get_frontend_session_payload(self) -> dict[str, Any]:
        return self.frontend_sessions.snapshot()

    def open_frontend_session(self, payload: FrontendSessionRequest) -> dict[str, Any]:
        return self.frontend_sessions.open(self._validated_frontend_client_id(payload), page=payload.page)

    def heartbeat_frontend_session(self, payload: FrontendSessionRequest) -> dict[str, Any]:
        return self.frontend_sessions.heartbeat(self._validated_frontend_client_id(payload), page=payload.page)

    def close_frontend_session(self, payload: FrontendSessionRequest) -> dict[str, Any]:
        return self.frontend_sessions.close(self._validated_frontend_client_id(payload))

    def save_settings_payload(self, payload: SettingsSaveRequest) -> dict[str, Any]:
        existing_api_key = self.settings.summary_api_key or ""
        next_api_key = existing_api_key if payload.keepExistingApiKey and not payload.summaryApiKey.strip() else payload.summaryApiKey
        save_env_settings(
            self.env_path,
            {
                "SUMMARY_API_BASE_URL": payload.summaryApiBaseUrl,
                "SUMMARY_API_KEY": next_api_key,
                "SUMMARY_API_MODEL": payload.summaryApiModel,
                "TRANSCRIBE_BACKEND": payload.transcribeBackend,
            },
        )
        self.reload()
        return self.get_settings_payload()

    def test_summary_connection(self) -> dict[str, Any]:
        return self._serialize_test_result(self.summary_service.test_summary_connection(self.settings))

    def test_summary_connection_with_payload(self, payload: SettingsSaveRequest) -> dict[str, Any]:
        return self._serialize_test_result(self.summary_service.test_summary_connection(self._settings_from_payload(payload)))

    def list_summary_models(self, payload: SettingsSaveRequest | None = None) -> dict[str, Any]:
        settings = self._settings_from_payload(payload) if payload else self.settings
        return self._serialize_test_result(self.summary_service.list_summary_models(settings))

    def test_summary_model(self, model_name: str | None, payload: SettingsSaveRequest | None = None) -> dict[str, Any]:
        settings = self._settings_from_payload(payload) if payload else self.settings
        return self._serialize_test_result(self.summary_service.test_summary_model_call(settings, model_name))

    def _settings_from_payload(self, payload: SettingsSaveRequest) -> Any:
        if payload.keepExistingApiKey and not payload.summaryApiKey.strip():
            next_api_key = self.settings.summary_api_key or ""
        else:
            next_api_key = payload.summaryApiKey
        return replace(
            self.settings,
            summary_api_base_url=payload.summaryApiBaseUrl.strip() or None,
            summary_api_key=next_api_key.strip() or None,
            summary_api_model=payload.summaryApiModel.strip() or self.settings.summary_api_model,
            transcribe_backend=payload.transcribeBackend.strip().lower() or self.settings.transcribe_backend,
        )

    def get_health_payload(self) -> dict[str, Any]:
        if not self.health_items:
            return serialize_health_payload([], has_run=False, status="idle")
        return serialize_health_payload(self.health_items, has_run=True, status=overall_status(self.health_items))

    def run_health_check(self) -> dict[str, Any]:
        self.health_items = run_startup_checks(self.settings)
        return self.get_health_payload()

    def get_platform_statuses(self) -> list[dict[str, Any]]:
        return [
            self.get_platform_status("douyin"),
            self.get_platform_status("bilibili"),
            serialize_platform_status(
                platform="xiaohongshu",
                title=PLATFORM_LABELS["xiaohongshu"],
                inspect_result=None,
                placeholder=True,
            ),
            serialize_platform_status(
                platform="wechat_butterfly",
                title=PLATFORM_LABELS["wechat_butterfly"],
                inspect_result=None,
                placeholder=True,
            ),
        ]

    def get_platform_status(self, platform: str) -> dict[str, Any]:
        if platform not in {"douyin", "bilibili"}:
            raise HTTPException(status_code=404, detail=f"暂不支持的平台授权类型：{platform}")
        try:
            inspect_result = inspect_managed_auth_profile(platform)
        except Exception as exc:
            inspect_result = {"ok": False, "summary": str(exc), "details": [str(exc)]}
        return serialize_platform_status(
            platform=platform,
            title=PLATFORM_LABELS[platform],
            inspect_result=inspect_result,
        )

    def open_platform_auth(self, platform: str) -> dict[str, Any]:
        if platform not in {"douyin", "bilibili"}:
            raise HTTPException(status_code=404, detail=f"暂不支持的平台授权类型：{platform}")
        browser_runtime = check_browser_runtime()
        if browser_runtime.status != "ok":
            detail = browser_runtime.detail
            if browser_runtime.recommendation:
                detail = f"{detail} {browser_runtime.recommendation}"
            raise HTTPException(status_code=503, detail=detail)
        launch_managed_auth_browser(platform)
        return serialize_platform_status(
            platform=platform,
            title=PLATFORM_LABELS[platform],
            inspect_result={
                "ok": False,
                "tone": "checking",
                "statusLabel": "等待检查",
                "summary": "授权浏览器已打开。请先在弹出的浏览器里完成登录，再点击检查状态。",
                "details": ["已启动工具内授权浏览器。完成登录后，请返回工作台手动检查状态。"],
            },
        )

    def list_runs_payload(self) -> list[dict[str, Any]]:
        return [serialize_run_list_item(item) for item in self._list_run_items()]

    def get_run_payload(self, run_id: str) -> dict[str, Any]:
        item = self._get_run_item(run_id)
        artifacts = self.orchestrator.load_run(item.run_dir)
        templates = serialize_template_catalog(self.summary_service.list_runtime_templates(), artifacts=artifacts)
        return serialize_run_workspace(item, artifacts, templates=templates)

    def get_download_file(self, run_id: str, artifact_name: str) -> Path:
        item = self._get_run_item(run_id)
        artifacts = self.orchestrator.load_run(item.run_dir)
        for name, path in build_download_items(artifacts).items():
            if name == artifact_name:
                return path
        raise HTTPException(status_code=404, detail=f"未找到对应产物：{artifact_name}")

    def create_share_link_task(self, payload: ShareLinkTaskRequest) -> str:
        request = JobRequest(
            entry_type="share_link",
            payload={"share_url": payload.shareUrl},
            summary_model=payload.summaryModel or self.settings.summary_api_model,
            transcribe_backend=(payload.transcribeBackend or self.settings.transcribe_backend).strip().lower(),
            browser_profiles=self._browser_profiles(),
        )
        orchestrator = self.orchestrator
        return self.task_registry.start(lambda progress: self._run_pipeline_task(orchestrator, request, progress))

    def create_local_media_task(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        summary_model: str | None,
        transcribe_backend: str | None,
    ) -> str:
        request = JobRequest(
            entry_type="local_media",
            payload={"file_name": file_name, "file_bytes": file_bytes},
            summary_model=summary_model or self.settings.summary_api_model,
            transcribe_backend=(transcribe_backend or self.settings.transcribe_backend).strip().lower(),
        )
        orchestrator = self.orchestrator
        return self.task_registry.start(lambda progress: self._run_pipeline_task(orchestrator, request, progress))

    def create_text_file_task(self, *, file_name: str, file_bytes: bytes, summary_model: str | None) -> str:
        request = JobRequest(
            entry_type="text_file",
            payload={"file_name": file_name, "file_bytes": file_bytes},
            summary_model=summary_model or self.settings.summary_api_model,
        )
        orchestrator = self.orchestrator
        return self.task_registry.start(lambda progress: self._run_pipeline_task(orchestrator, request, progress))

    def create_pasted_text_task(self, payload: PastedTextTaskRequest) -> str:
        request = JobRequest(
            entry_type="pasted_text",
            payload={"text": payload.text},
            summary_model=payload.summaryModel or self.settings.summary_api_model,
        )
        orchestrator = self.orchestrator
        return self.task_registry.start(lambda progress: self._run_pipeline_task(orchestrator, request, progress))

    def create_recovery_upload_task(self, files: list[InMemoryUpload]) -> str:
        orchestrator = self.orchestrator
        return self.task_registry.start(lambda progress: self._run_recovery_upload_task(orchestrator, files, progress))

    def resume_first_pass_task(self, run_id: str, summary_model: str | None = None) -> str:
        item = self._get_run_item(run_id)
        orchestrator = self.orchestrator
        return self.task_registry.start(
            lambda progress: self._resume_first_pass_task(orchestrator, item.run_dir, summary_model, progress)
        )

    def resume_templates_task(self, run_id: str, template_id: str | None, summary_model: str | None = None) -> str:
        item = self._get_run_item(run_id)
        template_to_run = (template_id or "").strip()
        if not template_to_run:
            raise HTTPException(status_code=400, detail="请选择一个二次深化 skill 后再执行。")
        orchestrator = self.orchestrator
        return self.task_registry.start(
            lambda progress: self._run_template_task(orchestrator, item.run_dir, template_to_run, summary_model, progress)
        )

    def get_task_payload(self, task_id: str) -> dict[str, Any]:
        snapshot = self.task_registry.get(task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"未找到任务：{task_id}")
        return snapshot.to_payload()

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        snapshot = self.task_registry.cancel(task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"未找到任务：{task_id}")
        return snapshot.to_payload()

    def find_resume_candidate(self) -> dict[str, Any] | None:
        result = self.orchestrator.find_resume_candidate(self.settings.output_dir)
        if not result:
            return None
        run_dir = Path(result["run_dir"])
        return {
            "runId": run_dir.name,
            "runDir": str(run_dir),
            "recoveryState": result["state"],
            "statusLabel": RECOVERY_LABELS.get(result["state"], result["state"]),
        }

    def _run_pipeline_task(self, orchestrator: PipelineOrchestrator, request: JobRequest, progress) -> dict[str, Any]:
        artifacts = orchestrator.run(request, progress_callback=progress)
        return self._task_result_for_artifacts(artifacts)

    def _resume_first_pass_task(
        self,
        orchestrator: PipelineOrchestrator,
        run_dir: Path,
        summary_model: str | None,
        progress,
    ) -> dict[str, Any]:
        artifacts = orchestrator.resume_first_pass(run_dir, progress_callback=progress, summary_model_override=summary_model)
        return self._task_result_for_artifacts(artifacts)

    def _run_template_task(
        self,
        orchestrator: PipelineOrchestrator,
        run_dir: Path,
        template_id: str,
        summary_model: str | None,
        progress,
    ) -> dict[str, Any]:
        artifacts = orchestrator.run_template(run_dir, template_id, progress_callback=progress, summary_model_override=summary_model)
        return self._task_result_for_artifacts(artifacts)

    def _run_recovery_upload_task(
        self,
        orchestrator: PipelineOrchestrator,
        files: list[InMemoryUpload],
        progress,
    ) -> dict[str, Any]:
        run_dir = orchestrator.materialize_uploaded_project_directory(files)
        progress(self._fake_status(phase="recovery", progress_percent=45, message="已恢复上传的项目目录。"))
        state = orchestrator.detect_recovery_state(run_dir)
        if state == "transcript_only":
            artifacts = orchestrator.resume_first_pass(
                run_dir,
                progress_callback=progress,
                summary_model_override=self.settings.summary_api_model,
            )
        else:
            artifacts = orchestrator.load_run(run_dir)
        return self._task_result_for_artifacts(artifacts)

    def _task_result_for_artifacts(self, artifacts) -> dict[str, Any]:
        run_dir = artifacts.transcript_bundle.output_dir
        return {"runId": run_dir.name, "runDir": str(run_dir)}

    def _browser_profiles(self) -> dict[str, str | None]:
        profiles: dict[str, str | None] = {}
        for platform in ("douyin", "bilibili"):
            auth_dir = get_managed_auth_user_data_dir(platform)
            default_dir = auth_dir / "Default"
            profiles[platform] = str(auth_dir) if default_dir.exists() else None
        return profiles

    def _list_run_items(self):
        return self.artifact_store.list_runs()

    def _get_run_item(self, run_id: str):
        for item in self._list_run_items():
            if item.run_dir.name == run_id:
                return item
        raise HTTPException(status_code=404, detail=f"未找到项目：{run_id}")

    def _fake_status(self, *, phase: str, progress_percent: int, message: str):
        return JobStatus(
            job_id="recovery-upload",
            state="running",
            phase=phase,
            progress_percent=progress_percent,
            message=message,
            phase_label={
                "recovery": "恢复项目",
                "artifact_write": "写入产物",
            }.get(phase, phase.replace("_", " ").title()),
        )

    def _serialize_test_result(self, result) -> dict[str, Any]:
        return {
            "ok": result.ok,
            "kind": result.kind,
            "message": result.message,
            "rawPreview": result.raw_preview,
            "requestSummary": result.request_summary,
            "statusCode": result.status_code,
            "modelName": result.model_name,
            "models": result.models,
        }

    def _validated_frontend_client_id(self, payload: FrontendSessionRequest) -> str:
        client_id = (payload.clientId or "").strip()
        if not client_id:
            raise HTTPException(status_code=400, detail="frontend clientId 不能为空。")
        return client_id


class FrontendSessionTracker:
    def __init__(self, timeout_seconds: float = 25.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def open(self, client_id: str, *, page: str | None = None) -> dict[str, Any]:
        return self._touch(client_id, page=page)

    def heartbeat(self, client_id: str, *, page: str | None = None) -> dict[str, Any]:
        return self._touch(client_id, page=page)

    def close(self, client_id: str) -> dict[str, Any]:
        with self._lock:
            self._cleanup_stale_locked()
            self._sessions.pop(client_id, None)
            return self._snapshot_locked()

    def has_active_session(self) -> bool:
        return bool(self.snapshot()["active"])

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._cleanup_stale_locked()
            return self._snapshot_locked()

    def _touch(self, client_id: str, *, page: str | None = None) -> dict[str, Any]:
        now_epoch = time.time()
        now_mono = time.monotonic()
        with self._lock:
            self._cleanup_stale_locked(now_mono)
            session = self._sessions.get(client_id, {})
            session["clientId"] = client_id
            session["page"] = page or session.get("page")
            session["lastSeenAt"] = now_epoch
            session["lastSeenMonotonic"] = now_mono
            self._sessions[client_id] = session
            return self._snapshot_locked()

    def _cleanup_stale_locked(self, now_mono: float | None = None) -> None:
        if not self._sessions:
            return
        current = now_mono if now_mono is not None else time.monotonic()
        stale_ids = [
            client_id
            for client_id, session in self._sessions.items()
            if current - float(session.get("lastSeenMonotonic", 0.0)) > self.timeout_seconds
        ]
        for client_id in stale_ids:
            self._sessions.pop(client_id, None)

    def _snapshot_locked(self) -> dict[str, Any]:
        last_seen_at = max((float(item.get("lastSeenAt", 0.0)) for item in self._sessions.values()), default=0.0)
        pages = sorted({str(item.get("page", "")).strip() for item in self._sessions.values() if str(item.get("page", "")).strip()})
        return {
            "active": bool(self._sessions),
            "sessionCount": len(self._sessions),
            "lastSeenAt": last_seen_at or None,
            "pages": pages,
            "timeoutSeconds": self.timeout_seconds,
        }


def create_web_app(
    frontend_sessions: FrontendSessionTracker | None = None,
    shutdown_handler: Callable[[], None] | None = None,
) -> FastAPI:
    backend = WorkspaceBackend(frontend_sessions=frontend_sessions)
    app = FastAPI(title="Synpture Workspace", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.workspace_backend = backend

    @app.get("/api/bootstrap")
    def get_bootstrap() -> dict[str, Any]:
        return backend.build_bootstrap_payload()

    @app.get("/api/runs")
    def get_runs() -> list[dict[str, Any]]:
        return backend.list_runs_payload()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return backend.get_run_payload(run_id)

    @app.get("/api/runs/{run_id}/download/{artifact_name}")
    def download_artifact(run_id: str, artifact_name: str):
        path = backend.get_download_file(run_id, artifact_name)
        return FileResponse(path, filename=path.name)

    @app.post("/api/tasks/share-link")
    def post_share_link_task(payload: ShareLinkTaskRequest) -> dict[str, Any]:
        return {"taskId": backend.create_share_link_task(payload)}

    @app.post("/api/tasks/local-media")
    async def post_local_media_task(
        file: UploadFile = File(...),
        summaryModel: str | None = Form(None),
        transcribeBackend: str | None = Form(None),
    ) -> dict[str, Any]:
        return {
            "taskId": backend.create_local_media_task(
                file_name=file.filename or "uploaded.bin",
                file_bytes=await file.read(),
                summary_model=summaryModel,
                transcribe_backend=transcribeBackend,
            )
        }

    @app.post("/api/tasks/text-file")
    async def post_text_file_task(
        file: UploadFile = File(...),
        summaryModel: str | None = Form(None),
    ) -> dict[str, Any]:
        return {
            "taskId": backend.create_text_file_task(
                file_name=file.filename or "uploaded.txt",
                file_bytes=await file.read(),
                summary_model=summaryModel,
            )
        }

    @app.post("/api/tasks/pasted-text")
    def post_pasted_text_task(payload: PastedTextTaskRequest) -> dict[str, Any]:
        return {"taskId": backend.create_pasted_text_task(payload)}

    @app.post("/api/tasks/recovery/uploaded-dir")
    async def post_recovery_upload_task(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        uploads = [InMemoryUpload(name=file.filename or "file.bin", data=await file.read()) for file in files]
        return {"taskId": backend.create_recovery_upload_task(uploads)}

    @app.post("/api/runs/{run_id}/resume-first-pass")
    def post_resume_first_pass(run_id: str, payload: ModelTestRequest) -> dict[str, Any]:
        return {"taskId": backend.resume_first_pass_task(run_id, payload.modelName)}

    @app.post("/api/runs/{run_id}/resume-templates")
    def post_resume_templates(run_id: str, payload: ResumeTemplatesRequest) -> dict[str, Any]:
        return {"taskId": backend.resume_templates_task(run_id, payload.templateId, payload.summaryModel)}

    @app.post("/api/runs/{run_id}/templates/{template_id}")
    def post_run_template(run_id: str, template_id: str, payload: ResumeTemplatesRequest) -> dict[str, Any]:
        return {"taskId": backend.resume_templates_task(run_id, template_id, payload.summaryModel)}

    @app.get("/api/tasks/{task_id}/status")
    def get_task_status(task_id: str) -> dict[str, Any]:
        return backend.get_task_payload(task_id)

    @app.post("/api/tasks/{task_id}/cancel")
    def post_task_cancel(task_id: str) -> dict[str, Any]:
        return backend.cancel_task(task_id)

    @app.get("/api/health")
    def get_health() -> dict[str, Any]:
        return backend.get_health_payload()

    @app.post("/api/health/run")
    def run_health() -> dict[str, Any]:
        return backend.run_health_check()

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return backend.get_settings_payload()

    @app.get("/api/runtime/transcription-capability")
    def get_transcription_capability() -> dict[str, Any]:
        return backend.get_transcription_capability_payload()

    @app.get("/api/runtime/resources")
    def get_runtime_resources() -> dict[str, Any]:
        return backend.get_runtime_resources_payload()

    @app.post("/api/runtime/resources/{resource_id}/download")
    def post_runtime_resource_download(resource_id: str) -> dict[str, Any]:
        return backend.start_runtime_resource_download_payload(resource_id)

    @app.get("/api/runtime/resources/{resource_id}/status")
    def get_runtime_resource_status(resource_id: str) -> dict[str, Any]:
        return backend.get_runtime_resource_status_payload(resource_id)

    @app.post("/api/runtime/resources/{resource_id}/upload")
    async def post_runtime_resource_upload(resource_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        return backend.install_runtime_resource_upload_payload(resource_id, file.filename or "resource.bin", await file.read())

    @app.post("/api/runtime/transcription-preference")
    def post_transcription_preference(payload: TranscriptionPreferenceRequest) -> dict[str, Any]:
        return backend.save_transcription_preference_payload(payload)

    @app.get("/api/runtime/frontend-session")
    def get_frontend_session() -> dict[str, Any]:
        return backend.get_frontend_session_payload()

    @app.post("/api/runtime/frontend-session/open")
    def post_frontend_session_open(payload: FrontendSessionRequest) -> dict[str, Any]:
        return backend.open_frontend_session(payload)

    @app.post("/api/runtime/frontend-session/heartbeat")
    def post_frontend_session_heartbeat(payload: FrontendSessionRequest) -> dict[str, Any]:
        return backend.heartbeat_frontend_session(payload)

    @app.post("/api/runtime/frontend-session/close")
    def post_frontend_session_close(payload: FrontendSessionRequest) -> dict[str, Any]:
        return backend.close_frontend_session(payload)

    @app.post("/api/runtime/shutdown")
    def post_runtime_shutdown() -> dict[str, Any]:
        if shutdown_handler is None:
            raise HTTPException(status_code=503, detail="当前运行实例不支持远程退出。")
        threading.Thread(target=shutdown_handler, name="synpture-runtime-shutdown", daemon=True).start()
        return {"ok": True, "message": "退出请求已发送。"}

    @app.post("/api/settings")
    def post_settings(payload: SettingsSaveRequest) -> dict[str, Any]:
        return backend.save_settings_payload(payload)

    @app.post("/api/settings/test-connection")
    async def post_settings_test_connection(request: Request) -> dict[str, Any]:
        payload_data = await _read_optional_json_body(request)
        if payload_data:
            return backend.test_summary_connection_with_payload(SettingsSaveRequest(**payload_data))
        return backend.test_summary_connection()

    @app.get("/api/settings/models")
    def get_settings_models() -> dict[str, Any]:
        return backend.list_summary_models()

    @app.post("/api/settings/models")
    def post_settings_models(payload: SettingsSaveRequest) -> dict[str, Any]:
        return backend.list_summary_models(payload)

    @app.post("/api/settings/test-model")
    def post_settings_test_model(payload: SettingsTestRequest) -> dict[str, Any]:
        return backend.test_summary_model(payload.modelName, payload)

    @app.post("/api/auth/{platform}/open")
    def post_auth_open(platform: str) -> dict[str, Any]:
        return backend.open_platform_auth(platform)

    @app.get("/api/auth/{platform}/status")
    def get_auth_status(platform: str) -> dict[str, Any]:
        return backend.get_platform_status(platform)

    @app.get("/", response_class=HTMLResponse)
    def get_workspace_index() -> HTMLResponse:
        return HTMLResponse(
            content=_render_workspace_index(),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    @app.get("/index.html", response_class=HTMLResponse)
    def get_workspace_index_file() -> HTMLResponse:
        return HTMLResponse(
            content=_render_workspace_index(),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    app.mount("/shared-assets", StaticFiles(directory=SHARED_ASSET_ROOT), name="shared_assets")
    app.mount("/", StaticFiles(directory=WORKSPACE_UI_ROOT, html=True), name="workspace_ui")
    return app


async def _read_optional_json_body(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        return {}
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _render_workspace_index() -> str:
    html = WORKSPACE_INDEX_PATH.read_text(encoding="utf-8")
    html = html.replace("./src/styles.css", f"./src/styles.css?v={_asset_version(WORKSPACE_STYLES_PATH)}")
    html = html.replace("./src/app.js", f"./src/app.js?v={_asset_version(WORKSPACE_APP_JS_PATH)}")
    return html


def _asset_version(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except FileNotFoundError:
        return 0
