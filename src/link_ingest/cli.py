from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from src.config import Settings, load_settings
from src.link_ingest.models import LinkIngestResult, LinkSample
from src.link_ingest.pipeline import LinkIngestPipeline
from src.link_ingest.reporting import write_batch_reports
from src.link_ingest.yt_dlp_client import YtDlpClient
from src.transcriber import transcribe_video
from src.utils import ensure_directory


DEFAULT_SAMPLE_FIELDS = ["sample_id", "platform_hint", "url", "title_hint", "cookies_profile", "notes"]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    samples = _load_samples(Path(args.samples), sample_filter=set(args.sample_id or []))
    if not samples:
        raise SystemExit("No samples were loaded. Check the CSV path and --sample-id filters.")

    settings = load_settings(args.env_file)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = ensure_directory(Path(args.output_root) / f"batch_{timestamp}")

    pipeline = LinkIngestPipeline(
        metadata_client=YtDlpClient(
            cookies_file=Path(args.cookies_file) if args.cookies_file else None,
            cookies_from_browser=args.cookies_from_browser,
            subtitle_languages=[item.strip() for item in args.subtitle_languages.split(",") if item.strip()],
        ),
        transcriber=LocalMediaTranscriber(settings),
    )

    results: list[LinkIngestResult] = []
    for index, sample in enumerate(samples, start=1):
        print(f"[{index}/{len(samples)}] Running sample {sample.sample_id} ({sample.url})")
        result = pipeline.run_sample(sample, output_root)
        results.append(result)
        status = "SUCCESS" if result.success else "FAILED"
        print(f"  -> {status}: {result.final_method or result.failure_reason}")

    json_path, csv_path, md_path = write_batch_reports(output_root, results)
    print("")
    print(f"Batch complete. Output directory: {output_root}")
    print(f"- JSON report: {json_path}")
    print(f"- CSV report: {csv_path}")
    print(f"- Markdown report: {md_path}")
    return 0


class LocalMediaTranscriber:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe_media(self, media_path: Path, output_dir: Path) -> str:
        ensure_directory(output_dir)
        result = transcribe_video(media_path, output_dir, self.settings)
        return result.transcript_text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project 0 link ingest verification runner.")
    parser.add_argument("--samples", required=True, help="CSV file containing link samples.")
    parser.add_argument("--sample-id", action="append", help="Run only selected sample_id values.")
    parser.add_argument("--output-root", default="output/link_ingest_lab", help="Directory for batch outputs.")
    parser.add_argument("--env-file", help="Optional .env file path for local transcribe settings.")
    parser.add_argument("--cookies-file", help="Optional cookies.txt path for yt-dlp.")
    parser.add_argument("--cookies-from-browser", help="Optional browser name for yt-dlp cookiesfrombrowser.")
    parser.add_argument(
        "--subtitle-languages",
        default="zh-Hans,zh-CN,zh,en",
        help="Comma-separated subtitle language preference order.",
    )
    return parser


def _load_samples(path: Path, sample_filter: set[str] | None = None) -> list[LinkSample]:
    rows = _read_tabular_rows(path)
    if not rows:
        return []

    header = [str(item or "").strip() for item in rows[0]]
    missing = [field for field in ("sample_id", "url") if field not in header]
    if missing:
        raise ValueError(f"Missing required sample columns: {', '.join(missing)}")

    samples: list[LinkSample] = []
    for raw_row in rows[1:]:
        row = {header[index]: str(raw_row[index] or "").strip() for index in range(min(len(header), len(raw_row)))}
        sample_id = row.get("sample_id", "")
        url = row.get("url", "")
        if not sample_id or not url:
            continue
        if sample_filter and sample_id not in sample_filter:
            continue
        samples.append(
            LinkSample(
                sample_id=sample_id,
                url=url,
                platform_hint=row.get("platform_hint") or None,
                title_hint=row.get("title_hint") or None,
                cookies_profile=row.get("cookies_profile") or None,
                notes=row.get("notes", ""),
            )
        )
    return samples


def _read_tabular_rows(path: Path) -> list[list[str]]:
    if zipfile.is_zipfile(path):
        return _read_xlsx_rows(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [list(row) for row in csv.reader(handle)]


def _read_xlsx_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as workbook:
        shared_strings = _read_shared_strings(workbook)
        sheet_root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))

    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows: list[list[str]] = []
    for row in sheet_root.findall(".//x:sheetData/x:row", namespace):
        values: list[str] = []
        current_column = 0
        for cell in row.findall("x:c", namespace):
            ref = cell.attrib.get("r", "")
            target_column = _column_index_from_ref(ref)
            while current_column < target_column:
                values.append("")
                current_column += 1
            values.append(_cell_value(cell, namespace, shared_strings))
            current_column += 1
        rows.append(values)
    return rows


def _read_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    items: list[str] = []
    for node in root.findall("x:si", namespace):
        parts = [text_node.text or "" for text_node in node.findall(".//x:t", namespace)]
        items.append("".join(parts))
    return items


def _cell_value(cell: ET.Element, namespace: dict[str, str], shared_strings: list[str]) -> str:
    value_node = cell.find("x:v", namespace)
    if value_node is None or value_node.text is None:
        inline_text = [node.text or "" for node in cell.findall(".//x:t", namespace)]
        return "".join(inline_text).strip()

    raw = value_node.text
    if cell.attrib.get("t") == "s":
        try:
            return shared_strings[int(raw)].strip()
        except Exception:
            return raw.strip()
    return raw.strip()


def _column_index_from_ref(ref: str) -> int:
    letters = "".join(char for char in ref if char.isalpha()).upper()
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return max(0, index - 1)


if __name__ == "__main__":
    raise SystemExit(main())
