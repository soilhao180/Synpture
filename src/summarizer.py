from __future__ import annotations

from src.config import Settings
from src.models import FirstPassResult, TemplateResult, TestResult, TranscriptBundle, TranscriptResult
from src.summarizers.openai_compatible import OpenAICompatibleSummarizer
from src.template_registry import list_template_definitions, load_template_definition


def run_first_pass(
    transcript_result: TranscriptBundle | TranscriptResult,
    settings: Settings,
    *,
    summary_model_override: str | None = None,
) -> FirstPassResult:
    summarizer = _build_remote_summarizer(settings, model_name=summary_model_override)
    try:
        return summarizer.run_first_pass(transcript_result)
    except Exception as exc:
        raise RuntimeError(f"首轮标准底稿必须使用远程总结模型，当前调用失败。原因：{exc}") from exc


def run_template_pass(
    first_pass_result: FirstPassResult,
    template_id: str,
    settings: Settings,
    *,
    summary_model_override: str | None = None,
) -> TemplateResult:
    template_definition = load_template_definition(template_id)
    summarizer = _build_remote_summarizer(settings, model_name=summary_model_override)
    try:
        return summarizer.run_template_pass(first_pass_result, template_definition)
    except Exception as exc:
        raise RuntimeError(f"二轮模板必须使用远程总结模型，当前调用失败。原因：{exc}") from exc


def list_runtime_templates():
    return list_template_definitions()


def test_summary_connection(settings: Settings) -> TestResult:
    return _build_remote_summarizer(settings).ping()


def list_summary_models(settings: Settings) -> TestResult:
    return _build_remote_summarizer(settings).list_models()


def test_summary_model_call(settings: Settings, model_name: str | None = None) -> TestResult:
    return _build_remote_summarizer(settings, model_name=model_name).test_model_call(model_name=model_name)


def _build_remote_summarizer(
    settings: Settings,
    model_name: str | None = None,
) -> OpenAICompatibleSummarizer:
    if not settings.summary_api_key:
        raise RuntimeError("未配置 SUMMARY_API_KEY，无法测试或调用远程总结模型。")
    return OpenAICompatibleSummarizer(
        api_key=settings.summary_api_key,
        model=model_name or settings.summary_api_model,
        base_url=settings.summary_api_base_url,
    )
