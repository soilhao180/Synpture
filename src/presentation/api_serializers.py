from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import Settings
from src.diagnostics import DiagnosticItem
from src.models import FirstPassResult, RunArtifacts, RunListItem, TemplateResult, TranscriptSegment
from src.transcription_runtime import TranscriptionCapability


ENTRY_LABELS = {
    "share_link": "分享链接",
    "local_media": "本地媒体",
    "text_file": "文本输入",
    "pasted_text": "文本输入",
}

RECOVERY_LABELS = {
    "transcript_only": "已完成转录",
    "first_pass_only": "第一稿已完成",
    "partial_templates": "已有部分模板结果",
    "completed": "模板深化已完成",
}

STATUS_TONES = {
    "transcript_only": "idle",
    "first_pass_only": "warn",
    "partial_templates": "ready",
    "completed": "ready",
}

HEALTH_TONES = {"idle": "idle", "ok": "ready", "warn": "idle", "error": "error"}


def serialize_settings(settings: Settings) -> dict[str, Any]:
    return {
        "outputDir": str(settings.output_dir),
        "transcribeBackend": settings.transcribe_backend,
        "summaryApiBaseUrl": settings.summary_api_base_url or "",
        "summaryApiModel": settings.summary_api_model,
        "summaryApiKeyMask": mask_api_key(settings.summary_api_key or ""),
        "summaryApiKeyConfigured": bool(settings.summary_api_key),
    }


def serialize_diagnostic_item(item: DiagnosticItem) -> dict[str, Any]:
    return {
        "ok": item.status == "ok",
        "status": item.status,
        "detail": item.detail,
        "recommendation": item.recommendation,
        "name": item.name,
    }


def serialize_transcription_capability(capability: TranscriptionCapability) -> dict[str, Any]:
    return {
        "gpuStatus": capability.gpu_status,
        "gpuReason": capability.gpu_reason,
        "gpuRecoverable": capability.gpu_recoverable,
        "cpuFallbackAvailable": capability.cpu_fallback_available,
        "preferredBackend": capability.preferred_backend,
        "allowCpuFallback": capability.allow_cpu_fallback,
        "decisionRequired": capability.decision_required,
        "nvidiaDetected": capability.nvidia_detected,
        "cpuReason": capability.cpu_reason,
        "gpuDetails": capability.gpu_details,
    }


def serialize_health_payload(
    items: list[DiagnosticItem],
    *,
    has_run: bool,
    status: str,
) -> dict[str, Any]:
    status_text = {
        "idle": "未运行",
        "ok": "可运行",
        "warn": "需要关注",
        "error": "存在问题",
    }.get(status, "未知")
    state_label_map = {
        "idle": "未运行",
        "ok": "正常",
        "warn": "待处理",
        "error": "异常",
    }
    return {
        "hasRun": has_run,
        "status": status,
        "statusText": status_text,
        "checks": [
            {
                "label": item.name,
                "state": item.status,
                "stateLabel": state_label_map.get(item.status, item.status),
                "tone": HEALTH_TONES.get(item.status, "idle"),
                "detail": item.detail,
                "recommendation": item.recommendation,
            }
            for item in items
        ],
    }


def serialize_platform_status(
    *,
    platform: str,
    title: str,
    inspect_result: dict[str, Any] | None,
    placeholder: bool = False,
) -> dict[str, Any]:
    if placeholder:
        return {
            "platform": platform,
            "title": title,
            "tone": "idle",
            "statusLabel": "待接入",
            "available": False,
            "summary": "当前仅保留页面位置。",
            "details": [],
            "actions": [],
            "placeholder": True,
        }

    inspect_result = inspect_result or {}
    ok = bool(inspect_result.get("ok"))
    summary = str(inspect_result.get("summary") or "")
    details = [str(item) for item in inspect_result.get("details", []) if str(item).strip()]
    tone = str(inspect_result.get("tone") or ("ready" if ok else "pending"))
    status_label = str(inspect_result.get("statusLabel") or ("可用" if ok else "等待授权"))
    return {
        "platform": platform,
        "title": title,
        "tone": tone,
        "statusLabel": status_label,
        "available": ok,
        "summary": summary,
        "details": details,
        "actions": ["open", "status"],
        "placeholder": False,
    }


def serialize_run_list_item(item: RunListItem) -> dict[str, Any]:
    effective_state = effective_recovery_state(item)
    return {
        "id": item.run_dir.name,
        "title": item.title,
        "entryType": normalize_entry_type(item.entry_type),
        "entryLabel": ENTRY_LABELS.get(item.entry_type, item.entry_type),
        "statusLabel": RECOVERY_LABELS.get(effective_state, effective_state),
        "recoveryState": effective_state,
        "updatedAt": format_timestamp(item.updated_at),
        "progressPercent": item.progress_percent,
        "summary": RECOVERY_LABELS.get(effective_state, effective_state),
        "runDir": str(item.run_dir),
        "sourceNote": short_run_path(item.run_dir),
        "runName": item.run_dir.name,
        "tone": STATUS_TONES.get(effective_state, "idle"),
    }


def serialize_run_workspace(
    item: RunListItem,
    artifacts: RunArtifacts,
    *,
    templates: list[dict[str, Any]],
) -> dict[str, Any]:
    source = artifacts.transcript_bundle.source
    effective_state = effective_recovery_state(item)
    current_status = artifacts.status_history[-1] if artifacts.status_history else None

    payload: dict[str, Any] = {
        "id": item.run_dir.name,
        "title": item.title,
        "sourceLabel": f"{ENTRY_LABELS.get(item.entry_type, item.entry_type)} / {source.display_name}",
        "runDir": str(item.run_dir),
        "runName": item.run_dir.name,
        "entryType": normalize_entry_type(item.entry_type),
        "stageLabel": RECOVERY_LABELS.get(effective_state, effective_state),
        "recoveryState": effective_state,
        "createdAt": pick_created_at(item, artifacts),
        "updatedAt": format_timestamp(item.updated_at),
        "progress": serialize_progress(item, artifacts),
        "alerts": build_alerts(effective_state, artifacts),
        "transcriptSection": serialize_transcript_section(artifacts),
        "skillOptions": templates,
        "nextStep": build_next_step(effective_state),
        "errorMessage": artifacts.error_message,
        "currentPhase": current_status.phase if current_status is not None else None,
        "currentMessage": current_status.message if current_status is not None else None,
    }

    if artifacts.first_pass_result is not None:
        payload["firstPass"] = serialize_first_pass(artifacts.first_pass_result)

    skill_results = serialize_template_results(artifacts.template_results)
    if skill_results:
        payload["skillResults"] = skill_results

    return payload


def serialize_template_catalog(
    template_definitions: list[Any],
    *,
    artifacts: RunArtifacts | None = None,
) -> list[dict[str, Any]]:
    completed = set(artifacts.template_results) if artifacts is not None else set()
    return [
        {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "completed": template.id in completed,
            "statusLabel": "已生成" if template.id in completed else "等待",
            "source": getattr(template, "source", "system"),
            "editable": bool(getattr(template, "editable", False)),
            "version": getattr(template, "version", None),
            "promptInstructions": getattr(template, "prompt_instructions", ""),
        }
        for template in template_definitions
    ]


def serialize_progress(item: RunListItem, artifacts: RunArtifacts) -> dict[str, Any]:
    current = artifacts.status_history[-1] if artifacts.status_history else None
    history: list[dict[str, Any]] = []
    for entry in artifacts.status_history:
        label = getattr(entry, "phase_label", "") or getattr(entry, "phase", "")
        detail = getattr(entry, "message", "") or label
        history.append(
            {
                "label": label,
                "detail": detail,
                "updatedAt": getattr(entry, "updated_at", item.updated_at),
                "progressPercent": getattr(entry, "progress_percent", item.progress_percent),
            }
        )

    detail_lines: list[str] = []
    if current is not None and current.error_code:
        detail_lines.append(f"{current.error_code}: {current.error_detail or ''}".strip())
    if artifacts.error_message:
        detail_lines.append(artifacts.error_message)

    phase_label = RECOVERY_LABELS.get(effective_recovery_state(item), item.state)
    if current is not None:
        phase_label = current.phase_label or current.phase or phase_label
    subtitle = current.message if current is not None and current.message else phase_label

    return {
        "title": "当前进度",
        "phaseLabel": phase_label,
        "subtitle": subtitle,
        "progressPercent": current.progress_percent if current is not None else item.progress_percent,
        "detailLines": detail_lines,
        "history": history,
    }


def serialize_transcript_section(artifacts: RunArtifacts) -> dict[str, Any]:
    source = artifacts.transcript_bundle.source
    timeline_text = build_timeline_text(artifacts.transcript_bundle.segments, artifacts.transcript_bundle.transcript_text)
    return {
        "title": "原始转录稿",
        "sourceName": source.display_name,
        "body": clip_text(artifacts.transcript_bundle.transcript_text, limit=1800),
        "timelineText": clip_text(timeline_text, limit=4200),
        "hasTimeline": bool(artifacts.transcript_bundle.segments),
    }


def serialize_first_pass(first_pass: FirstPassResult) -> dict[str, Any]:
    return {
        "title": "第一稿",
        "headline": first_pass.generated_title or "",
        "oneLineVerdict": first_pass.one_line_verdict,
        "valueRating": first_pass.value_rating,
        "valueReason": first_pass.value_reason,
        "generatedTitle": first_pass.generated_title,
        "highValuePoints": first_pass.high_value_points[:6],
        "objectiveContext": first_pass.objective_context[:6],
        "cleanedTranscript": clip_text(first_pass.cleaned_transcript, limit=3200),
        "rawTranscriptReference": clip_text(first_pass.raw_transcript_reference, limit=1800),
        "draftParagraphs": [
            {
                "index": item.index,
                "text": clip_text(item.text, limit=900),
                "valueLevel": item.value_level,
                "reason": item.reason,
            }
            for item in first_pass.draft_paragraphs
        ],
        "uncertaintyNotes": first_pass.uncertainty_notes[:6],
        "needsHumanCheckTimestamps": first_pass.needs_human_check_timestamps[:6],
    }


def serialize_template_results(template_results: dict[str, TemplateResult]) -> list[dict[str, Any]]:
    cards = []
    for template_id, result in sorted(template_results.items()):
        overview = result.overview
        if not overview and result.section_summaries:
            overview = result.section_summaries[0].summary
        cards.append(
            {
                "id": template_id,
                "title": result.template_name or template_id,
                "tag": "已生成",
                "overview": clip_text(overview, limit=900),
                "keyPoints": result.key_points[:6],
                "sections": [
                    {
                        "title": item.title,
                        "summary": clip_text(item.summary, limit=360),
                        "bullets": item.bullets[:4],
                    }
                    for item in result.section_summaries[:4]
                ],
                "fields": {key: value for key, value in list(result.template_fields.items())[:6]},
                "source": result.template_source,
                "version": result.template_version,
            }
        )
    return cards


def build_download_items(artifacts: RunArtifacts) -> dict[str, Path]:
    items: dict[str, Path] = {
        artifacts.transcript_path.name: artifacts.transcript_path,
        artifacts.segments_path.name: artifacts.segments_path,
    }
    optional = [
        artifacts.chunks_path,
        artifacts.input_source_path,
        artifacts.acquisition_result_path,
        artifacts.gpu_diagnostics_json_path,
        artifacts.gpu_diagnostics_md_path,
        artifacts.first_pass_json_path,
        artifacts.first_pass_markdown_path,
    ]
    for path in optional:
        if path is not None:
            items[path.name] = path
    for path in artifacts.template_json_paths.values():
        items[path.name] = path
    for path in artifacts.template_markdown_paths.values():
        items[path.name] = path
    return items


def normalize_entry_type(entry_type: str) -> str:
    if entry_type in {"text_file", "pasted_text"}:
        return "text_input"
    return entry_type


def effective_recovery_state(item: RunListItem) -> str:
    if item.has_templates and item.state == "succeeded":
        return "completed"
    return item.recovery_state


def build_alerts(recovery_state: str, artifacts: RunArtifacts) -> list[str]:
    alerts = [RECOVERY_LABELS.get(recovery_state, recovery_state)]
    if artifacts.error_message:
        alerts.append(artifacts.error_message)
    elif recovery_state == "transcript_only":
        alerts.append("当前阶段只有原始转录稿，下一步应生成第一稿。")
    elif recovery_state == "first_pass_only":
        alerts.append("第一稿已完成，下一步请选择一个模板做二次深化。")
    elif recovery_state == "partial_templates":
        alerts.append("已有部分模板结果，可以继续选择其他模板深化。")
    else:
        alerts.append("当前项目已有完整的模板深化结果，可继续查看或重跑指定模板。")
    return alerts


def build_next_step(recovery_state: str) -> dict[str, str]:
    if recovery_state == "transcript_only":
        return {"title": "下一步", "description": "生成第一稿"}
    if recovery_state == "first_pass_only":
        return {"title": "下一步", "description": "选择一个模板做二次深化"}
    if recovery_state == "partial_templates":
        return {"title": "下一步", "description": "继续选择其他模板深化"}
    return {"title": "当前状态", "description": "可查看已有结果或重跑指定模板"}


def short_run_path(run_dir: Path) -> str:
    parts = list(run_dir.parts)
    if "output" in parts:
        index = parts.index("output")
        tail = parts[index:]
        return "/".join(tail[-2:]) if len(tail) >= 2 else "/".join(tail)
    return run_dir.name


def pick_created_at(item: RunListItem, artifacts: RunArtifacts) -> str:
    if artifacts.status_history:
        created_at = getattr(artifacts.status_history[0], "created_at", None)
        if created_at:
            return format_timestamp(str(created_at))
    return format_timestamp(item.updated_at)


def build_timeline_text(segments: list[TranscriptSegment], transcript_text: str) -> str:
    if not segments:
        return transcript_text
    lines = []
    for segment in segments:
        stamp = format_timeline_range(segment.start, segment.end)
        text = " ".join(segment.text.split())
        lines.append(f"[{stamp}] {text}".strip())
    return "\n".join(lines)


def format_timeline_range(start: float | None, end: float | None) -> str:
    start_text = format_seconds(start)
    end_text = format_seconds(end)
    if start_text and end_text:
        return f"{start_text} - {end_text}"
    return start_text or end_text or "--:--"


def format_seconds(value: float | None) -> str:
    if value is None:
        return ""
    total_seconds = max(0, int(value))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_timestamp(value: str) -> str:
    compact = value.strip()
    if len(compact) >= 16:
        return compact[:16]
    return compact


def clip_text(value: str | None, *, limit: int) -> str:
    compact = (value or "").replace("\r", "")
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}..."


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:3]}{'*' * max(4, len(api_key) - 5)}{api_key[-2:]}"
