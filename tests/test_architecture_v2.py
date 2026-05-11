from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from src.application.pipeline_orchestrator import PipelineOrchestrator
from src.config import Settings
from src.domain.job import JobRequest
from src.infrastructure.artifact_store import LocalArtifactStore
from src.models import (
    AcquisitionResult,
    FirstPassResult,
    LowValueSegment,
    TemplateResult,
    TemplateSection,
    TranscriptBundle,
    TranscriptSegment,
)
from src.services.acquisition_service import AcquisitionService
from src.services.transcription_service import TranscriptionService


class AcquisitionServiceTests(unittest.TestCase):
    def test_pasted_text_request_becomes_acquisition_result(self) -> None:
        run_dir = Path("output") / "v2_acquisition_pasted_text"
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            settings = Settings(output_dir=run_dir)
            request = JobRequest(entry_type="pasted_text", payload={"text": "alpha\n\nbeta"})
            result = AcquisitionService().acquire(request, run_dir, settings)
            self.assertEqual(result.acquisition.acquisition_mode, "direct_text")
            self.assertEqual(len(result.acquisition.segments), 2)
            self.assertIn("alpha", result.acquisition.display_text)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


class TranscriptionServiceTests(unittest.TestCase):
    def test_text_acquisition_skips_media_transcription(self) -> None:
        run_dir = Path("output") / "v2_transcription_text"
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            source_request = JobRequest(entry_type="pasted_text", payload={"text": "one\n\ntwo"})
            settings = Settings(output_dir=run_dir)
            acquisition = AcquisitionService().acquire(source_request, run_dir, settings).acquisition
            bundle = TranscriptionService().build_transcript_bundle(acquisition, run_dir, settings)
            self.assertEqual(bundle.model_used, "text-input")
            self.assertEqual(bundle.backend_used, "direct_text")
            self.assertGreaterEqual(len(bundle.chunks), 1)
            self.assertEqual(bundle.transcript_text, "one\n\ntwo")
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


class LocalArtifactStoreTests(unittest.TestCase):
    def test_v2_manifest_round_trip_and_recovery_detection(self) -> None:
        output_root = Path("output") / "v2_artifact_store"
        shutil.rmtree(output_root, ignore_errors=True)
        output_root.mkdir(parents=True, exist_ok=True)
        try:
            store = LocalArtifactStore(output_root)
            request = JobRequest(entry_type="pasted_text", payload={"text": "hello world"}, summary_model="demo-model")
            run_dir = store.create_run("job-1", "demo", request=request)
            bundle = _build_text_bundle(run_dir, "hello world")
            store.write_input_source(run_dir, bundle)
            store.write_transcript_bundle(run_dir, bundle)

            loaded = store.load_run(run_dir, Settings(output_dir=output_root))
            self.assertEqual(loaded.transcript_bundle.transcript_text, "hello world")
            self.assertEqual(store.detect_recovery_state(run_dir), "transcript_only")
            self.assertTrue((run_dir / "job.json").exists())
        finally:
            shutil.rmtree(output_root, ignore_errors=True)


class PipelineOrchestratorTests(unittest.TestCase):
    def test_python_service_interface_runs_first_pass_and_template(self) -> None:
        output_root = Path("output") / "v2_orchestrator"
        shutil.rmtree(output_root, ignore_errors=True)
        output_root.mkdir(parents=True, exist_ok=True)
        try:
            settings = Settings(output_dir=output_root, summary_api_model="fake-summary-model")
            orchestrator = PipelineOrchestrator(settings, summary_service=FakeSummaryService())
            request = JobRequest(
                entry_type="pasted_text",
                payload={"text": "line one\n\nline two"},
                summary_model="template-model",
            )

            artifacts = orchestrator.run(request)
            self.assertIsNotNone(artifacts.first_pass_result)
            self.assertEqual(artifacts.selected_summary_model, "template-model")
            self.assertTrue((artifacts.transcript_bundle.output_dir / "first_pass.json").exists())
            self.assertEqual(orchestrator.detect_recovery_state(artifacts.transcript_bundle.output_dir), "first_pass_only")

            template_artifacts = orchestrator.run_template(artifacts.transcript_bundle.output_dir, "minimal-summary")
            self.assertIn("minimal-summary", template_artifacts.template_results)
            self.assertEqual(template_artifacts.active_template_id, "minimal-summary")
        finally:
            shutil.rmtree(output_root, ignore_errors=True)


class FakeSummaryService:
    def run_first_pass(self, transcript_result, settings: Settings, *, summary_model_override: str | None = None) -> FirstPassResult:
        del settings
        model = summary_model_override or "fake-summary-model"
        return FirstPassResult(
            provider="fake",
            model=model,
            cleaned_transcript=transcript_result.transcript_text,
            one_line_verdict="值得看，核心价值在于 point one",
            headline_verdict="useful",
            value_rating="high",
            value_reason="contains signal",
            high_value_points=["point one"],
            objective_context=["context one"],
            low_value_segments=[LowValueSegment(start=None, end=None, reason="filler", excerpt="n/a")],
            raw_transcript_reference=transcript_result.transcript_text,
        )

    def run_template_pass(
        self,
        first_pass_result: FirstPassResult,
        template_id: str,
        settings: Settings,
        *,
        summary_model_override: str | None = None,
    ) -> TemplateResult:
        del settings
        model = summary_model_override or "fake-summary-model"
        return TemplateResult(
            template_id=template_id,
            template_name=template_id,
            provider="fake",
            model=model,
            overview=first_pass_result.headline_verdict,
            key_points=list(first_pass_result.high_value_points),
            section_summaries=[TemplateSection(title="section", summary="summary", bullets=["bullet"])],
        )


def _build_text_bundle(run_dir: Path, text: str) -> TranscriptBundle:
    source_obj = AcquisitionService().acquire(
        JobRequest(entry_type="pasted_text", payload={"text": text}),
        run_dir,
        Settings(output_dir=run_dir),
    ).acquisition.source
    acquisition = AcquisitionResult(
        source=source_obj,
        acquisition_mode="direct_text",
        display_text=text,
        segments=[TranscriptSegment(index=1, start=None, end=None, text=text)],
    )
    return TranscriptBundle(
        source=source_obj,
        acquisition=acquisition,
        output_dir=run_dir,
        backend_used="direct_text",
        model_used="text-input",
        language="zh",
        transcript_text=text,
        segments=[TranscriptSegment(index=1, start=None, end=None, text=text)],
        chunks=[],
        notes=["unit test"],
    )
