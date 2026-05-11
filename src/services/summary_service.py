from __future__ import annotations

from src.config import Settings
from src.domain.errors import AppError
from src.models import FirstPassResult, TemplateResult, TestResult, TranscriptBundle, TranscriptResult
from src.summarizer import (
    list_runtime_templates,
    list_summary_models,
    run_first_pass,
    run_template_pass,
    test_summary_connection,
    test_summary_model_call,
)


class SummaryService:
    def run_first_pass(
        self,
        transcript_result: TranscriptBundle | TranscriptResult,
        settings: Settings,
        *,
        summary_model_override: str | None = None,
    ) -> FirstPassResult:
        try:
            return run_first_pass(
                transcript_result,
                settings,
                summary_model_override=summary_model_override,
            )
        except Exception as exc:
            raise self._map_error(exc, "summary.first_pass_failed", "第一稿标准底稿生成失败") from exc

    def run_template_pass(
        self,
        first_pass_result: FirstPassResult,
        template_id: str,
        settings: Settings,
        *,
        summary_model_override: str | None = None,
    ) -> TemplateResult:
        try:
            return run_template_pass(
                first_pass_result,
                template_id,
                settings,
                summary_model_override=summary_model_override,
            )
        except Exception as exc:
            raise self._map_error(exc, "summary.template_failed", "第二轮模板生成失败") from exc

    def list_runtime_templates(self):
        return list_runtime_templates()

    def test_summary_connection(self, settings: Settings) -> TestResult:
        try:
            return test_summary_connection(settings)
        except Exception as exc:
            return self._build_test_error_result(
                exc,
                kind="summary_connection",
                fallback_message="总结服务连接测试失败。",
            )

    def list_summary_models(self, settings: Settings) -> TestResult:
        try:
            return list_summary_models(settings)
        except Exception as exc:
            return self._build_test_error_result(
                exc,
                kind="summary_list_models",
                fallback_message="获取可用模型失败。",
            )

    def test_summary_model_call(self, settings: Settings, model_name: str | None = None) -> TestResult:
        try:
            return test_summary_model_call(settings, model_name=model_name)
        except Exception as exc:
            return self._build_test_error_result(
                exc,
                kind="summary_model_call",
                fallback_message="测试模型调用失败。",
                model_name=model_name or settings.summary_api_model,
            )

    def _map_error(self, exc: Exception, default_code: str, default_message: str) -> AppError:
        text = str(exc)
        if "SUMMARY_API_KEY" in text:
            return AppError(
                error_code="summary.api_not_configured",
                message="总结模型未配置。",
                detail=text,
            )
        return AppError(
            error_code=default_code,
            message=default_message,
            detail=text,
        )

    def _build_test_error_result(
        self,
        exc: Exception,
        *,
        kind: str,
        fallback_message: str,
        model_name: str | None = None,
    ) -> TestResult:
        mapped = self._map_error(exc, "summary.test_failed", fallback_message)
        detail = (mapped.detail or str(exc) or "").strip()
        message = detail or mapped.message or fallback_message
        return TestResult(
            ok=False,
            kind=kind,
            message=message,
            raw_preview=detail[:500] if detail and detail != message else None,
            model_name=model_name,
        )
