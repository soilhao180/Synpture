from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Literal


WorkspaceView = Literal[
    "local_media",
    "share_link",
    "text_input",
    "recovery",
    "result_workspace",
]

LOCAL_MEDIA_VIEW: WorkspaceView = "local_media"
SHARE_LINK_VIEW: WorkspaceView = "share_link"
TEXT_INPUT_VIEW: WorkspaceView = "text_input"
RECOVERY_VIEW: WorkspaceView = "recovery"
RESULT_WORKSPACE_VIEW: WorkspaceView = "result_workspace"

WORKSPACE_VIEWS: tuple[WorkspaceView, ...] = (
    LOCAL_MEDIA_VIEW,
    SHARE_LINK_VIEW,
    TEXT_INPUT_VIEW,
    RECOVERY_VIEW,
    RESULT_WORKSPACE_VIEW,
)

WORKSPACE_SESSION_DEFAULTS: dict[str, Any] = {
    "workspace_view": LOCAL_MEDIA_VIEW,
    "history_panel_open": True,
    "settings_panel_open": True,
    "selected_run_dir": None,
    "selected_history_run_state": None,
}


def ensure_workspace_state(state: MutableMapping[str, Any]) -> None:
    for key, value in WORKSPACE_SESSION_DEFAULTS.items():
        state.setdefault(key, value)
    state["workspace_view"] = normalize_workspace_view(state.get("workspace_view"))


def normalize_workspace_view(value: str | None) -> WorkspaceView:
    if value in WORKSPACE_VIEWS:
        return value
    return LOCAL_MEDIA_VIEW


def next_workspace_view_for_artifacts(artifacts: object | None) -> WorkspaceView:
    if artifacts is not None:
        return RESULT_WORKSPACE_VIEW
    return LOCAL_MEDIA_VIEW


def resolve_history_action_label(recovery_state: str | None, *, has_templates: bool = False) -> str:
    if recovery_state == "transcript_only":
        return "继续生成第一稿"
    if recovery_state in {"first_pass_only", "partial_templates"}:
        return "加载并继续加工"
    if has_templates:
        return "加载结果"
    return "加载结果"


def resolve_result_primary_action(recovery_state: str | None) -> str | None:
    if recovery_state == "transcript_only":
        return "继续生成第一稿"
    if recovery_state == "partial_templates":
        return "继续生成模板"
    return None


def should_render_first_pass(recovery_state: str | None) -> bool:
    return recovery_state != "transcript_only"


def should_render_template_results(recovery_state: str | None, *, has_templates: bool = False) -> bool:
    return has_templates or recovery_state == "partial_templates"
