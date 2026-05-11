from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from src.link_ingest.models import LinkIngestResult, PlatformReport
from src.utils import write_json, write_text


def build_platform_reports(results: list[LinkIngestResult]) -> list[PlatformReport]:
    grouped: dict[str, list[LinkIngestResult]] = defaultdict(list)
    for result in results:
        grouped[result.platform].append(result)

    reports: list[PlatformReport] = []
    for platform, items in sorted(grouped.items()):
        success_count = sum(1 for item in items if item.success)
        sample_count = len(items)
        success_rate = success_count / sample_count if sample_count else 0.0
        requires_cookies_count = sum(1 for item in items if item.requires_cookies)
        method_counter = Counter(item.final_method for item in items if item.final_method)
        failure_counter = Counter(item.failure_reason for item in items if item.failure_reason)
        reports.append(
            PlatformReport(
                platform=platform,
                sample_count=sample_count,
                success_count=success_count,
                success_rate=success_rate,
                requires_cookies_count=requires_cookies_count,
                support_level=_classify_support_level(success_rate, success_count, sample_count, requires_cookies_count),
                top_methods=[name for name, _ in method_counter.most_common(3)],
                top_failure_reasons=[name for name, _ in failure_counter.most_common(3)],
            )
        )
    return reports


def write_batch_reports(output_dir: Path, results: list[LinkIngestResult]) -> tuple[Path, Path, Path]:
    reports = build_platform_reports(results)
    json_path = write_json(
        output_dir / "batch_results.json",
        {
            "results": [_serialize_result(item) for item in results],
            "platform_reports": [_serialize_platform_report(report) for report in reports],
        },
    )
    csv_path = _write_results_csv(output_dir / "batch_results.csv", results)
    md_path = _write_markdown_report(output_dir / "platform_support_report.md", results, reports)
    return json_path, csv_path, md_path


def _write_results_csv(path: Path, results: list[LinkIngestResult]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "platform",
                "success",
                "final_method",
                "final_text_length",
                "requires_cookies",
                "failure_reason",
                "url",
                "title",
                "extractor_key",
                "run_dir",
            ],
        )
        writer.writeheader()
        for item in results:
            writer.writerow(
                {
                    "sample_id": item.sample_id,
                    "platform": item.platform,
                    "success": item.success,
                    "final_method": item.final_method or "",
                    "final_text_length": item.final_text_length,
                    "requires_cookies": item.requires_cookies,
                    "failure_reason": item.failure_reason or "",
                    "url": item.url,
                    "title": item.title or "",
                    "extractor_key": item.extractor_key or "",
                    "run_dir": str(item.run_dir) if item.run_dir else "",
                }
            )
    return path


def _write_markdown_report(path: Path, results: list[LinkIngestResult], reports: list[PlatformReport]) -> Path:
    total = len(results)
    success_count = sum(1 for item in results if item.success)
    lines = [
        "# Project 0 Link Ingest Report",
        "",
        f"- Sample count: {total}",
        f"- Success count: {success_count}",
        f"- Success rate: {_format_rate(success_count, total)}",
        "",
        "## Platform Support",
        "",
    ]
    for report in reports:
        lines.extend(
            [
                f"### {report.platform}",
                f"- Support level: {report.support_level}",
                f"- Samples: {report.sample_count}",
                f"- Successes: {report.success_count}",
                f"- Success rate: {_format_rate(report.success_count, report.sample_count)}",
                f"- Requires cookies: {report.requires_cookies_count}",
                f"- Top methods: {', '.join(report.top_methods) if report.top_methods else '-'}",
                f"- Top failure reasons: {', '.join(report.top_failure_reasons) if report.top_failure_reasons else '-'}",
                "",
            ]
        )

    lines.extend(["## Sample Outcomes", ""])
    for item in results:
        lines.extend(
            [
                f"### {item.sample_id} ({item.platform})",
                f"- Success: {item.success}",
                f"- Final method: {item.final_method or '-'}",
                f"- Failure reason: {item.failure_reason or '-'}",
                f"- Requires cookies: {item.requires_cookies}",
                f"- Text length: {item.final_text_length}",
                f"- Run dir: {item.run_dir or '-'}",
                "",
            ]
        )
    return write_text(path, "\n".join(lines).strip() + "\n")


def _classify_support_level(
    success_rate: float,
    success_count: int,
    sample_count: int,
    requires_cookies_count: int,
) -> str:
    if sample_count == 0:
        return "未验证"
    cookie_ratio = requires_cookies_count / sample_count
    if success_rate >= 0.8 and cookie_ratio <= 0.25:
        return "正式支持"
    if success_rate >= 0.5:
        return "Beta"
    if success_count > 0:
        return "实验性"
    return "暂不支持"


def _serialize_result(item: LinkIngestResult) -> dict[str, object]:
    return {
        "sample_id": item.sample_id,
        "url": item.url,
        "normalized_url": item.normalized_url,
        "platform": item.platform,
        "extractor_key": item.extractor_key,
        "title": item.title,
        "success": item.success,
        "final_method": item.final_method,
        "final_text_length": item.final_text_length,
        "requires_cookies": item.requires_cookies,
        "support_evidence": item.support_evidence,
        "failure_reason": item.failure_reason,
        "run_dir": str(item.run_dir) if item.run_dir else None,
        "artifacts": [{"kind": artifact.kind, "path": str(artifact.path)} for artifact in item.artifacts],
        "attempts": [
            {
                "method": attempt.method,
                "status": attempt.status,
                "detail": attempt.detail,
                "started_at": attempt.started_at,
                "finished_at": attempt.finished_at,
                "requires_cookies": attempt.requires_cookies,
                "error_type": attempt.error_type,
                "text_length": attempt.text_length,
                "artifacts": [{"kind": artifact.kind, "path": str(artifact.path)} for artifact in attempt.artifacts],
            }
            for attempt in item.attempts
        ],
    }


def _serialize_platform_report(report: PlatformReport) -> dict[str, object]:
    return {
        "platform": report.platform,
        "sample_count": report.sample_count,
        "success_count": report.success_count,
        "success_rate": report.success_rate,
        "requires_cookies_count": report.requires_cookies_count,
        "support_level": report.support_level,
        "top_methods": report.top_methods,
        "top_failure_reasons": report.top_failure_reasons,
    }


def _format_rate(success_count: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{(success_count / total) * 100:.1f}%"
