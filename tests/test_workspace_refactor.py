from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

from src.infrastructure.artifact_store import LocalArtifactStore
from src.presentation.config_io import save_env_settings
from src.presentation.runtime_snapshot import build_workspace_runtime_snapshot
from src.presentation.state import (
    LOCAL_MEDIA_VIEW,
    RESULT_WORKSPACE_VIEW,
    next_workspace_view_for_artifacts,
    resolve_history_action_label,
    resolve_result_primary_action,
)
from src.utils import write_json


class RunListTests(unittest.TestCase):
    def test_list_runs_sorts_and_maps_recovery_state(self) -> None:
        output_root = Path("output") / "workspace_run_list"
        shutil.rmtree(output_root, ignore_errors=True)
        output_root.mkdir(parents=True, exist_ok=True)
        try:
            _write_run(
                output_root / "older_run",
                entry_type="local_media",
                title="older.mp4",
                updated_at="2026-04-27 10:00:00",
                with_first_pass=True,
            )
            _write_run(
                output_root / "newer_run",
                entry_type="share_link",
                title="https://example.com/demo",
                updated_at="2026-04-28 11:30:00",
                with_first_pass=True,
                with_template=True,
            )
            (output_root / "managed_auth_profiles").mkdir(parents=True, exist_ok=True)

            items = LocalArtifactStore(output_root).list_runs()

            self.assertEqual([item.run_dir.name for item in items], ["newer_run", "older_run"])
            self.assertEqual(items[0].title, "https://example.com/demo")
            self.assertEqual(items[0].entry_type, "share_link")
            self.assertEqual(items[0].recovery_state, "partial_templates")
            self.assertTrue(items[0].has_templates)
            self.assertEqual(items[1].recovery_state, "first_pass_only")
            self.assertEqual(items[1].progress_percent, 92)
        finally:
            shutil.rmtree(output_root, ignore_errors=True)

    def test_recovered_progress_uses_artifacts_over_stale_manifest(self) -> None:
        output_root = Path("output") / "workspace_recovered_progress"
        shutil.rmtree(output_root, ignore_errors=True)
        output_root.mkdir(parents=True, exist_ok=True)
        try:
            _write_run(
                output_root / "restored_first_pass",
                entry_type="share_link",
                title="https://example.com/first-pass",
                updated_at="2026-05-04 22:35:35",
                with_first_pass=True,
                manifest_progress=45,
            )
            _write_run(
                output_root / "restored_completed",
                entry_type="share_link",
                title="https://example.com/completed",
                updated_at="2026-05-04 22:36:35",
                with_first_pass=True,
                with_template=True,
                manifest_progress=45,
            )

            items = {item.run_dir.name: item for item in LocalArtifactStore(output_root).list_runs()}

            self.assertEqual(items["restored_first_pass"].progress_percent, 92)
            self.assertEqual(items["restored_completed"].progress_percent, 100)
        finally:
            shutil.rmtree(output_root, ignore_errors=True)


class EnvWritebackTests(unittest.TestCase):
    def test_save_env_settings_preserves_comments_and_unknown_keys(self) -> None:
        temp_dir = Path("output") / "workspace_env_writeback"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        env_path = temp_dir / ".env"
        original_api_key = os.environ.get("SUMMARY_API_KEY")
        original_model = os.environ.get("SUMMARY_API_MODEL")
        try:
            env_path.write_text(
                "# comment line\nUNKNOWN_KEY=keep-me\nSUMMARY_API_MODEL=old-model\n",
                encoding="utf-8",
            )
            save_env_settings(
                env_path,
                {
                    "SUMMARY_API_MODEL": "gpt-5.5",
                    "SUMMARY_API_KEY": "",
                    "TRANSCRIBE_BACKEND": "local",
                },
            )

            content = env_path.read_text(encoding="utf-8")
            self.assertIn("# comment line", content)
            self.assertIn("UNKNOWN_KEY=keep-me", content)
            self.assertIn("SUMMARY_API_MODEL=gpt-5.5", content)
            self.assertIn("SUMMARY_API_KEY=", content)
            self.assertIn("TRANSCRIBE_BACKEND=local", content)
            self.assertEqual(os.environ.get("SUMMARY_API_MODEL"), "gpt-5.5")
            self.assertEqual(os.environ.get("SUMMARY_API_KEY"), "")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            _restore_env("SUMMARY_API_KEY", original_api_key)
            _restore_env("SUMMARY_API_MODEL", original_model)
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    def test_load_settings_reloads_latest_env_values(self) -> None:
        temp_dir = Path("output") / "workspace_env_reload"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        env_path = temp_dir / ".env"
        env_path.write_text("SUMMARY_API_MODEL=gpt-5.4\nSUMMARY_API_KEY=sk-old\n", encoding="utf-8")
        try:
            from src.config import load_settings

            first = load_settings(env_path)
            self.assertEqual(first.summary_api_model, "gpt-5.4")
            self.assertEqual(first.summary_api_key, "sk-old")

            env_path.write_text("SUMMARY_API_MODEL=gpt-5.5\nSUMMARY_API_KEY=sk-new\n", encoding="utf-8")
            second = load_settings(env_path)
            self.assertEqual(second.summary_api_model, "gpt-5.5")
            self.assertEqual(second.summary_api_key, "sk-new")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class WorkspaceStateTests(unittest.TestCase):
    def test_result_artifacts_switch_workspace_to_result_view(self) -> None:
        self.assertEqual(next_workspace_view_for_artifacts(object()), RESULT_WORKSPACE_VIEW)
        self.assertEqual(next_workspace_view_for_artifacts(None), LOCAL_MEDIA_VIEW)

    def test_recovery_actions_match_expected_copy(self) -> None:
        self.assertEqual(resolve_history_action_label("transcript_only"), "继续生成第一稿")
        self.assertEqual(resolve_history_action_label("first_pass_only"), "加载并继续加工")
        self.assertEqual(resolve_history_action_label("partial_templates"), "加载并继续加工")
        self.assertEqual(resolve_history_action_label(None, has_templates=True), "加载结果")
        self.assertEqual(resolve_result_primary_action("transcript_only"), "继续生成第一稿")
        self.assertEqual(resolve_result_primary_action("partial_templates"), "继续生成模板")


class RuntimeSnapshotTests(unittest.TestCase):
    def test_runtime_snapshot_maps_real_run_data(self) -> None:
        output_root = Path("output") / "workspace_runtime_snapshot"
        shutil.rmtree(output_root, ignore_errors=True)
        output_root.mkdir(parents=True, exist_ok=True)
        try:
            _write_run(
                output_root / "run_20260428_090000",
                entry_type="share_link",
                title="https://example.com/demo",
                updated_at="2026-04-28 09:00:00",
                with_first_pass=True,
                with_template=True,
            )
            store = LocalArtifactStore(output_root)

            from src.config import Settings

            settings = Settings(output_dir=output_root)
            snapshot = build_workspace_runtime_snapshot(store, settings)

            self.assertEqual(snapshot["historyRuns"][0]["id"], "run_20260428_090000")
            self.assertEqual(snapshot["historyRuns"][0]["entryType"], "share_link")
            payload = snapshot["resultPayloads"]["run_20260428_090000"]
            self.assertEqual(payload["recoveryState"], "completed")
            self.assertIn("transcriptSection", payload)
            self.assertIn("firstPass", payload)
            self.assertIn("skillResults", payload)
            self.assertEqual(payload["nextStep"]["title"], "当前状态")
            self.assertTrue(snapshot["settingsFormState"]["outputDir"].endswith("workspace_runtime_snapshot"))
            self.assertIn("statusText", snapshot["healthCheckState"])
        finally:
            shutil.rmtree(output_root, ignore_errors=True)


def _write_run(
    run_dir: Path,
    *,
    entry_type: str,
    title: str,
    updated_at: str,
    with_first_pass: bool = False,
    with_template: bool = False,
    manifest_progress: int | None = None,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "job.json",
        {
            "entry_type": entry_type,
            "source_label": title,
            "state": "succeeded" if with_first_pass else "running",
            "progress_percent": (
                manifest_progress if manifest_progress is not None else 100 if with_template else 92 if with_first_pass else 68
            ),
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
    (run_dir / "transcript.txt").write_text("hello", encoding="utf-8")
    write_json(run_dir / "segments.json", {"segments": []})
    write_json(run_dir / "chunks.json", {"chunks": []})
    if with_first_pass:
        write_json(
            run_dir / "first_pass.json",
            {
                "provider": "test",
                "model": "test-model",
                "cleaned_transcript": "整理后的底稿",
                "one_line_verdict": "值得看，核心价值在于要点一",
                "headline_verdict": "可用",
                "value_rating": "high",
                "value_reason": "重点明确",
                "high_value_points": ["要点一"],
                "objective_context": ["背景一"],
                "low_value_segments": [],
                "raw_transcript_reference": "原始转录稿",
                "draft_paragraphs": [
                    {"index": 1, "text": "整理后的底稿", "value_level": "high", "reason": ""}
                ],
                "uncertainty_notes": [],
                "needs_human_check_timestamps": [],
                "warning": None,
            },
        )
    if with_template:
        write_json(
            run_dir / "template_minimal-summary.json",
            {
                "template_id": "minimal-summary",
                "template_name": "最小总结",
                "provider": "test",
                "model": "test-model",
                "overview": "模板结果概览",
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
