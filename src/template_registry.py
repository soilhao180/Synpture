from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from src.models import TemplateDefinition
from src.runtime_paths import bundled_path, get_custom_skills_root
from src.utils import timestamp_now


TEMPLATE_ROOT = bundled_path("templates", "skills")
TEMPLATE_OUTPUT_FIELDS = ["overview", "key_points", "section_summaries", "template_fields"]
NAME_MAX_LENGTH = 24
DESCRIPTION_MAX_LENGTH = 72
PROMPT_MAX_LENGTH = 12000
CUSTOM_TEMPLATE_PREFIX = "custom-"


def list_template_definitions() -> list[TemplateDefinition]:
    definitions: list[TemplateDefinition] = []
    definitions.extend(_list_definitions_from_root(TEMPLATE_ROOT, source="system", editable=False))
    definitions.extend(_list_definitions_from_root(_custom_template_root(), source="custom", editable=True))
    return [definition for definition in definitions if not definition.archived]


def list_custom_template_definitions(*, include_archived: bool = False) -> list[TemplateDefinition]:
    definitions = _list_definitions_from_root(_custom_template_root(), source="custom", editable=True)
    if include_archived:
        return definitions
    return [definition for definition in definitions if not definition.archived]


def load_template_definition(template_id: str) -> TemplateDefinition:
    system_definition = _load_from_root(TEMPLATE_ROOT, template_id, source="system", editable=False)
    if system_definition is not None:
        return system_definition

    custom_definition = _load_from_root(_custom_template_root(), template_id, source="custom", editable=True)
    if custom_definition is not None:
        return custom_definition

    archived_definition = _load_from_root(
        _custom_template_root() / "_archived",
        template_id,
        source="custom",
        editable=False,
        archived=True,
    )
    if archived_definition is not None:
        return archived_definition

    raise RuntimeError(f"未找到模板定义：{template_id}")


def create_custom_template_definition(name: str, description: str, prompt_instructions: str) -> TemplateDefinition:
    payload = _build_custom_template_payload(
        name=name,
        description=description,
        prompt_instructions=prompt_instructions,
        template_id=_generate_custom_template_id(name),
        version=uuid.uuid4().hex[:10],
    )
    template_dir = _custom_template_root() / payload["id"]
    _write_template_payload(template_dir, payload)
    return load_template_definition(payload["id"])


def update_custom_template_definition(
    template_id: str,
    *,
    name: str,
    description: str,
    prompt_instructions: str,
) -> TemplateDefinition:
    existing = load_template_definition(template_id)
    if existing.source != "custom" or not existing.editable:
        raise ValueError("系统级 skill 不允许修改。")

    existing_dir = _custom_template_root() / template_id
    if not existing_dir.exists():
        raise ValueError("未找到要修改的自定义 skill。")

    _archive_custom_template(existing_dir, template_id)
    payload = _build_custom_template_payload(
        name=name,
        description=description,
        prompt_instructions=prompt_instructions,
        template_id=_generate_custom_template_id(name),
        version=uuid.uuid4().hex[:10],
    )
    template_dir = _custom_template_root() / payload["id"]
    _write_template_payload(template_dir, payload)
    return load_template_definition(payload["id"])


def _list_definitions_from_root(root: Path, *, source: str, editable: bool) -> list[TemplateDefinition]:
    if not root.exists():
        return []

    definitions: list[TemplateDefinition] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name == "_archived":
            continue
        template_json = child / "template.json"
        if not template_json.exists():
            continue
        definitions.append(_load_template_definition(child, source=source, editable=editable))
    return definitions


def _custom_template_root() -> Path:
    return get_custom_skills_root()


def _load_from_root(
    root: Path,
    template_id: str,
    *,
    source: str,
    editable: bool,
    archived: bool = False,
) -> TemplateDefinition | None:
    template_dir = root / template_id
    template_json = template_dir / "template.json"
    if not template_json.exists():
        if root.name == "_archived":
            for candidate in root.glob(f"{template_id}-*/template.json"):
                return _load_template_definition(candidate.parent, source=source, editable=editable, archived=True)
        return None
    return _load_template_definition(template_dir, source=source, editable=editable, archived=archived)


def _load_template_definition(
    template_dir: Path,
    *,
    source: str,
    editable: bool,
    archived: bool = False,
) -> TemplateDefinition:
    payload = json.loads((template_dir / "template.json").read_text(encoding="utf-8"))
    template_source = str(payload.get("source", source)).strip() or source
    is_archived = bool(payload.get("archived", archived))
    return TemplateDefinition(
        id=str(payload.get("id", template_dir.name)).strip(),
        name=str(payload.get("name", template_dir.name)).strip(),
        description=str(payload.get("description", "")).strip(),
        input_fields=[str(item).strip() for item in payload.get("input_fields", []) if str(item).strip()],
        output_fields=[str(item).strip() for item in payload.get("output_fields", []) if str(item).strip()],
        prompt_instructions=str(payload.get("prompt_instructions", "")).strip(),
        fallback_rules=dict(payload.get("fallback_rules", {})),
        directory=template_dir,
        source=template_source,
        version=str(payload.get("version", "")).strip() or None,
        editable=template_source == "custom" and editable and not is_archived,
        archived=is_archived,
    )


def _build_custom_template_payload(
    *,
    name: str,
    description: str,
    prompt_instructions: str,
    template_id: str,
    version: str,
) -> dict[str, Any]:
    normalized_name = _normalize_limited_text(name, "skill 名称", NAME_MAX_LENGTH)
    normalized_description = _normalize_limited_text(description, "skill 简介", DESCRIPTION_MAX_LENGTH)
    normalized_prompt = str(prompt_instructions or "").strip()
    if not normalized_prompt:
        raise ValueError("Markdown 提示词不能为空。")
    if len(normalized_prompt) > PROMPT_MAX_LENGTH:
        raise ValueError(f"Markdown 提示词不能超过 {PROMPT_MAX_LENGTH} 个字符。")

    return {
        "id": template_id,
        "name": normalized_name,
        "description": normalized_description,
        "input_fields": [
            "cleaned_transcript",
            "headline_verdict",
            "value_rating",
            "value_reason",
            "high_value_points",
            "objective_context",
            "low_value_segments",
        ],
        "output_fields": TEMPLATE_OUTPUT_FIELDS,
        "prompt_instructions": normalized_prompt,
        "fallback_rules": {"mode": "custom_prompt"},
        "source": "custom",
        "version": version,
        "archived": False,
        "created_at": timestamp_now(),
    }


def _normalize_limited_text(value: str, field_name: str, max_length: int) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if not normalized:
        raise ValueError(f"{field_name}不能为空。")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name}不能超过 {max_length} 个字符。")
    return normalized


def _generate_custom_template_id(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    if not normalized:
        normalized = "skill"
    return f"{CUSTOM_TEMPLATE_PREFIX}{normalized[:28]}-{uuid.uuid4().hex[:8]}"


def _write_template_payload(template_dir: Path, payload: dict[str, Any]) -> None:
    template_dir.mkdir(parents=True, exist_ok=False)
    (template_dir / "template.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (template_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {payload['id']}\n"
        f"description: {payload['description']}\n"
        "---\n\n"
        f"# {payload['name']}\n\n"
        f"{payload['prompt_instructions']}\n",
        encoding="utf-8",
    )


def _archive_custom_template(template_dir: Path, template_id: str) -> None:
    archive_root = _custom_template_root() / "_archived"
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_dir = archive_root / f"{template_id}-{uuid.uuid4().hex[:8]}"
    shutil.move(str(template_dir), str(archive_dir))
    template_json = archive_dir / "template.json"
    payload = json.loads(template_json.read_text(encoding="utf-8"))
    payload["archived"] = True
    payload["archived_at"] = timestamp_now()
    template_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
