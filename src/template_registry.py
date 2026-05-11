from __future__ import annotations

import json
from pathlib import Path

from src.models import TemplateDefinition
from src.runtime_paths import bundled_path


TEMPLATE_ROOT = bundled_path("templates", "skills")


def list_template_definitions() -> list[TemplateDefinition]:
    if not TEMPLATE_ROOT.exists():
        return []

    definitions: list[TemplateDefinition] = []
    for child in sorted(TEMPLATE_ROOT.iterdir()):
        if not child.is_dir():
            continue
        template_json = child / "template.json"
        if not template_json.exists():
            continue
        definitions.append(load_template_definition(child.name))
    return definitions


def load_template_definition(template_id: str) -> TemplateDefinition:
    template_dir = TEMPLATE_ROOT / template_id
    template_json = template_dir / "template.json"
    if not template_json.exists():
        raise RuntimeError(f"未找到模板定义：{template_id}")

    payload = json.loads(template_json.read_text(encoding="utf-8"))
    return TemplateDefinition(
        id=str(payload.get("id", template_id)).strip(),
        name=str(payload.get("name", template_id)).strip(),
        description=str(payload.get("description", "")).strip(),
        input_fields=[str(item).strip() for item in payload.get("input_fields", []) if str(item).strip()],
        output_fields=[str(item).strip() for item in payload.get("output_fields", []) if str(item).strip()],
        prompt_instructions=str(payload.get("prompt_instructions", "")).strip(),
        fallback_rules=dict(payload.get("fallback_rules", {})),
        directory=template_dir,
    )
