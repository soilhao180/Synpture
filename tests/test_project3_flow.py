from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from app import find_resume_candidate, find_resume_candidate_for_run_dir
from src.artifacts import load_first_pass, load_template_result, serialize_first_pass, serialize_template_result
from src.models import FirstPassResult, LowValueSegment, TemplateResult, TemplateSection
from src.template_registry import create_custom_template_definition, list_template_definitions, load_template_definition, update_custom_template_definition
from src.utils import write_json


class TemplateRegistryTests(unittest.TestCase):
    def test_runtime_templates_are_discoverable(self) -> None:
        with unittest.mock.patch("src.template_registry.get_custom_skills_root", return_value=Path("output") / "empty_test_skills"):
            definitions = list_template_definitions()
        ids = {item.id for item in definitions}
        self.assertEqual(
            ids,
            {"study-deep-dive", "minimal-summary", "action-extraction", "course-notes", "expert-review"},
        )

    def test_custom_templates_are_created_and_editing_archives_old_version(self) -> None:
        temp_dir = Path("output") / "project3_custom_templates"
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            with unittest.mock.patch("src.template_registry.get_custom_skills_root", return_value=temp_dir / "skills"):
                created = create_custom_template_definition("短视频改写", "改写成短视频脚本", "# 目标\n- 改写成短视频脚本")
                self.assertEqual(created.source, "custom")
                self.assertTrue(created.editable)
                self.assertIn(created.id, {item.id for item in list_template_definitions()})

                updated = update_custom_template_definition(
                    created.id,
                    name="短视频改写新版",
                    description="改写成新版脚本",
                    prompt_instructions="# 目标\n- 改写成新版短视频脚本",
                )
                self.assertNotEqual(updated.id, created.id)
                self.assertTrue(updated.editable)
                archived = load_template_definition(created.id)
                self.assertTrue(archived.archived)
                self.assertFalse(archived.editable)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_system_template_cannot_be_edited(self) -> None:
        with self.assertRaises(ValueError):
            update_custom_template_definition(
                "expert-review",
                name="专业点评新版",
                description="不应该允许修改",
                prompt_instructions="# no",
            )


class ArtifactRoundTripTests(unittest.TestCase):
    def test_first_pass_round_trip(self) -> None:
        temp_dir = Path("output") / "project3_first_pass_round_trip"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            payload = FirstPassResult(
                provider="fallback",
                model="rule-based",
                cleaned_transcript="整理稿",
                one_line_verdict="值得看，核心价值在于点1",
                headline_verdict="一句话结论",
                value_rating="有部分价值",
                value_reason="有少量可保留信息。",
                high_value_points=["点1", "点2"],
                objective_context=["背景1"],
                low_value_segments=[LowValueSegment(start=0, end=10, reason="铺垫", excerpt="大家先别划走")],
                raw_transcript_reference="原始转录",
            )
            path = write_json(temp_dir / "first_pass.json", serialize_first_pass(payload))
            loaded = load_first_pass(path)
            self.assertEqual(loaded.headline_verdict, "一句话结论")
            self.assertEqual(loaded.low_value_segments[0].reason, "铺垫")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_template_round_trip(self) -> None:
        temp_dir = Path("output") / "project3_template_round_trip"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            payload = TemplateResult(
                template_id="expert-review",
                template_name="专业点评",
                provider="fallback",
                model="rule-based",
                overview="总览",
                key_points=["点1"],
                section_summaries=[TemplateSection(title="部分", summary="摘要", bullets=["子项"])],
                template_fields={"原文依据": ["点1"]},
            )
            path = write_json(temp_dir / "template_expert-review.json", serialize_template_result(payload))
            loaded = load_template_result(path)
            self.assertEqual(loaded.template_id, "expert-review")
            self.assertEqual(loaded.section_summaries[0].title, "部分")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class ResumeCandidateTests(unittest.TestCase):
    def test_resume_candidate_detects_transcript_only(self) -> None:
        temp_dir = Path("output") / "project3_resume_transcript_only"
        shutil.rmtree(temp_dir, ignore_errors=True)
        run_dir = temp_dir / "case1"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            (run_dir / "transcript.txt").write_text("ok", encoding="utf-8")
            (run_dir / "chunks.json").write_text('{"chunks":[]}', encoding="utf-8")
            state = find_resume_candidate(temp_dir)
            self.assertIsNotNone(state)
            self.assertEqual(state["state"], "transcript_only")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_candidate_for_run_dir_detects_first_pass_only(self) -> None:
        temp_dir = Path("output") / "project3_resume_first_pass_only"
        shutil.rmtree(temp_dir, ignore_errors=True)
        run_dir = temp_dir / "case1"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            (run_dir / "transcript.txt").write_text("ok", encoding="utf-8")
            (run_dir / "chunks.json").write_text('{"chunks":[]}', encoding="utf-8")
            (run_dir / "first_pass.json").write_text("{}", encoding="utf-8")
            self.assertEqual(find_resume_candidate_for_run_dir(run_dir), "first_pass_only")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_candidate_for_run_dir_detects_partial_templates(self) -> None:
        temp_dir = Path("output") / "project3_resume_partial_templates"
        shutil.rmtree(temp_dir, ignore_errors=True)
        run_dir = temp_dir / "case1"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            (run_dir / "transcript.txt").write_text("ok", encoding="utf-8")
            (run_dir / "chunks.json").write_text('{"chunks":[]}', encoding="utf-8")
            (run_dir / "first_pass.json").write_text("{}", encoding="utf-8")
            (run_dir / "template_expert-review.json").write_text("{}", encoding="utf-8")
            self.assertEqual(find_resume_candidate_for_run_dir(run_dir), "partial_templates")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
