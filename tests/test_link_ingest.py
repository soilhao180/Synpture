from __future__ import annotations

import sqlite3
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from src.link_ingest.models import LinkSample
from src.link_ingest.pipeline import LinkIngestPipeline
from src.link_ingest.platforms import detect_platform
from src.link_ingest.reporting import build_platform_reports
from src.link_ingest.subtitles import extract_text_from_subtitle_file
from src.share_link_ingest import build_node_env, inspect_managed_auth_profile, resolve_node_bin


class PlatformDetectionTests(unittest.TestCase):
    def test_detect_platform_variants(self) -> None:
        self.assertEqual(detect_platform("https://www.bilibili.com/video/BV1xx"), "bilibili")
        self.assertEqual(detect_platform("https://v.douyin.com/abcdef/"), "douyin")
        self.assertEqual(detect_platform("https://www.xiaohongshu.com/explore/abc"), "xiaohongshu")
        self.assertEqual(detect_platform("https://www.kuaishou.com/short-video/abc"), "kuaishou")


class SubtitleExtractionTests(unittest.TestCase):
    def test_extract_text_from_vtt(self) -> None:
        temp_dir = Path("output") / "project0_vtt_test"
        temp_dir.mkdir(parents=True, exist_ok=True)
        subtitle_path = temp_dir / "sample.vtt"
        try:
            subtitle_path.write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n你好\n\n00:00:01.000 --> 00:00:02.000\n世界\n",
                encoding="utf-8",
            )
            self.assertEqual(extract_text_from_subtitle_file(subtitle_path), "你好\n世界")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extract_text_from_json3(self) -> None:
        temp_dir = Path("output") / "project0_json3_test"
        temp_dir.mkdir(parents=True, exist_ok=True)
        subtitle_path = temp_dir / "sample.json3"
        try:
            subtitle_path.write_text(
                '{"events":[{"segs":[{"utf8":"你好"}]},{"segs":[{"utf8":"世界"}]}]}',
                encoding="utf-8",
            )
            self.assertEqual(extract_text_from_subtitle_file(subtitle_path), "你好\n世界")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class ReportingTests(unittest.TestCase):
    def test_platform_report_support_level(self) -> None:
        from src.link_ingest.models import LinkIngestResult

        results = [
            LinkIngestResult(
                sample_id="b1",
                url="https://www.bilibili.com/video/BV1",
                normalized_url="https://www.bilibili.com/video/BV1",
                platform="bilibili",
                extractor_key="BiliBili",
                title="ok",
                success=True,
                final_method="original_subtitle",
                final_text_length=50,
                requires_cookies=False,
            ),
            LinkIngestResult(
                sample_id="b2",
                url="https://www.bilibili.com/video/BV2",
                normalized_url="https://www.bilibili.com/video/BV2",
                platform="bilibili",
                extractor_key="BiliBili",
                title="ok2",
                success=True,
                final_method="audio_download_transcribe",
                final_text_length=80,
                requires_cookies=False,
            ),
        ]
        reports = build_platform_reports(results)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].support_level, "正式支持")


class ManagedAuthProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path("output") / "managed_auth_profile_tests"
        shutil.rmtree(self.temp_root, ignore_errors=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_bilibili_requires_all_critical_cookies(self) -> None:
        self._write_cookie_db(
            platform="bilibili",
            cookies=[
                (".bilibili.com", "SESSDATA"),
                (".bilibili.com", "DedeUserID"),
            ],
        )
        with patch("src.share_link_ingest.MANAGED_AUTH_ROOT", self.temp_root):
            payload = inspect_managed_auth_profile("bilibili")
        self.assertFalse(payload["ok"])
        self.assertTrue(any("缺少关键登录信息" in detail for detail in payload["details"]))

    def test_bilibili_is_ready_only_when_all_critical_cookies_exist(self) -> None:
        self._write_cookie_db(
            platform="bilibili",
            cookies=[
                (".bilibili.com", "SESSDATA"),
                (".bilibili.com", "DedeUserID"),
                (".bilibili.com", "bili_jct"),
            ],
        )
        with patch("src.share_link_ingest.MANAGED_AUTH_ROOT", self.temp_root):
            payload = inspect_managed_auth_profile("bilibili")
        self.assertTrue(payload["ok"])
        self.assertTrue(any("关键登录信息完整" in detail for detail in payload["details"]))

    def _write_cookie_db(self, *, platform: str, cookies: list[tuple[str, str]]) -> None:
        profile_dir = self.temp_root / platform / "chrome_user_data" / "Default" / "Network"
        profile_dir.mkdir(parents=True, exist_ok=True)
        cookies_path = profile_dir / "Cookies"
        conn = sqlite3.connect(cookies_path)
        try:
            conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
            conn.executemany("INSERT INTO cookies (host_key, name) VALUES (?, ?)", cookies)
            conn.commit()
        finally:
            conn.close()


class BundledBrowserRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path("output") / "bundled_browser_runtime_tests"
        shutil.rmtree(self.temp_root, ignore_errors=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_resolve_node_bin_prefers_bundled_runtime(self) -> None:
        bundled_node = self.temp_root / "third_party" / "node" / "node.exe"
        bundled_node.parent.mkdir(parents=True, exist_ok=True)
        bundled_node.write_bytes(b"")

        with (
            patch("src.share_link_ingest.bundled_path", side_effect=lambda *parts: self.temp_root.joinpath(*parts)),
            patch.dict("os.environ", {}, clear=False),
        ):
            self.assertEqual(resolve_node_bin(), str(bundled_node))

    def test_build_node_env_sets_bundled_chromium_and_node_path(self) -> None:
        bundled_node_modules = self.temp_root / "third_party" / "node_runtime" / "node_modules"
        bundled_chromium = self.temp_root / "third_party" / "chromium" / "chrome.exe"
        bundled_node_modules.mkdir(parents=True, exist_ok=True)
        bundled_chromium.parent.mkdir(parents=True, exist_ok=True)
        bundled_chromium.write_bytes(b"")

        with (
            patch("src.share_link_ingest.bundled_path", side_effect=lambda *parts: self.temp_root.joinpath(*parts)),
            patch.dict("os.environ", {}, clear=True),
        ):
            env = build_node_env()

        self.assertIn(str(bundled_node_modules), env["NODE_PATH"].split(";"))
        self.assertEqual(env["SHARE_LINK_CHROME_EXE"], str(bundled_chromium))


class PipelineTests(unittest.TestCase):
    def test_pipeline_uses_unified_video_transcribe_path(self) -> None:
        temp_dir = Path("output") / "project0_pipeline_test"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = LinkIngestPipeline(metadata_client=FakeMetadataClient(temp_dir), transcriber=FakeTranscriber())
            result = pipeline.run_sample(
                LinkSample(sample_id="case1", url="https://www.kuaishou.com/short-video/abc"),
                temp_dir,
            )
            self.assertTrue(result.success)
            self.assertEqual(result.final_method, "video_download_transcribe")
            self.assertEqual([attempt.method for attempt in result.attempts], [
                "subtitle_paths_disabled",
                "video_download_transcribe",
            ])
            self.assertEqual(result.attempts[0].status, "skipped")
            self.assertEqual(result.attempts[1].status, "success")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class FakeMetadataClient:
    def __init__(self, root: Path) -> None:
        self.root = root

    def extract_info(self, url: str) -> dict[str, object]:
        return {
            "webpage_url": url,
            "extractor_key": "Kwai",
            "title": "demo",
            "subtitles": {},
            "automatic_captions": {},
        }

    def download_subtitles(self, *, url: str, output_dir: Path, automatic: bool, available_languages: list[str]):
        raise AssertionError("download_subtitles should not be called when subtitle paths are disabled")

    def download_media(self, *, url: str, output_dir: Path, media_kind: str) -> Path:
        self.last_media_kind = media_kind
        video_path = output_dir / "video.mp4"
        video_path.write_bytes(b"video")
        return video_path


class FakeTranscriber:
    def transcribe_media(self, media_path: Path, output_dir: Path) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        return "可用文字"


if __name__ == "__main__":
    unittest.main()
