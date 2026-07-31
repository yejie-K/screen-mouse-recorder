from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.event_extraction import (  # noqa: E402
    OCRTextItem,
    RegionProfileError,
    RegionProfileReviewWorkspace,
    RegionScanJob,
    RegionScanConfig,
    convert_legacy_layout_profile,
    parse_metric_text,
    scan_all_extracted_frames,
)


class FakeRegionEngine:
    name = "fake-region-ocr"
    version = "1.0"

    def recognize(self, image_path: Path):
        frame = image_path.parent.name
        region = image_path.stem
        frame_number = 1 if frame.endswith("000001") else 2
        if region == "roi_power":
            return [OCRTextItem(f"战力{9 + frame_number}万", 0.96)], 0.01
        if region == "roi_unlock_trigger":
            return [OCRTextItem("新功能开启", 0.99)], 0.01
        if region == "roi_unlock_name":
            return [OCRTextItem("伙伴副本", 0.94)], 0.01
        return [], 0.01


class FakeSuggestionEngine:
    name = "fake-suggestion-ocr"
    version = "1.0"

    def recognize(self, image_path: Path):
        return [OCRTextItem("战力 11.04万", 0.99, (0, 0, 20, 10))], 0.02


class FakeStableMetricEngine:
    name = "fake-stable-metric-ocr"
    version = "1.0"

    def recognize(self, image_path: Path):
        return [OCRTextItem("战力10万", 0.95)], 0.01


class RegionScanTests(unittest.TestCase):
    def _profile(self, *, status: str = "complete") -> dict:
        region_status = "confirmed" if status == "complete" else "needs_review"
        return {
            "schema_version": "1.1",
            "game_id": "demo",
            "game_name": "测试游戏",
            "status": status,
            "scan_scope": "all_extracted_frames",
            "source_frame": {"width": 100, "height": 100},
            "regions": [
                {
                    "region_id": "roi_power",
                    "region_kind": "metric",
                    "rect_normalized": [0, 0, 0.5, 0.5],
                    "scene_hint": "主界面战力",
                    "sample_texts": ["战力10万"],
                    "sample_evidence": ["frame_001.png"],
                    "enabled": True,
                    "status": region_status,
                    "metric_key": "combat_power",
                    "parser": "numeric_cn",
                },
                {
                    "region_id": "roi_unlock_trigger",
                    "region_kind": "event",
                    "rect_normalized": [0.5, 0, 0.75, 0.5],
                    "scene_hint": "开放提示",
                    "sample_texts": ["新功能开启"],
                    "sample_evidence": ["frame_001.png"],
                    "enabled": True,
                    "status": region_status,
                    "region_group_id": "feature_unlock",
                    "region_role": "trigger",
                    "fixed_keywords": ["新功能开启"],
                    "mode_tag": "系统",
                    "event_tag": "新养成系统",
                },
                {
                    "region_id": "roi_unlock_name",
                    "region_kind": "event",
                    "rect_normalized": [0.75, 0, 1, 0.5],
                    "scene_hint": "开放名称",
                    "sample_texts": ["伙伴副本"],
                    "sample_evidence": ["frame_001.png"],
                    "enabled": True,
                    "status": region_status,
                    "region_group_id": "feature_unlock",
                    "region_role": "name",
                    "fixed_keywords": [],
                    "mode_tag": "系统",
                    "event_tag": "新养成系统",
                },
            ],
            "review": {
                "reviewer": "tester" if status == "complete" else "",
                "reviewed_at": "2026-07-21T18:00:00+08:00" if status == "complete" else "",
            },
        }

    def test_empty_draft_accepts_first_manual_sample_when_region_is_added(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            profile = self._profile(status="needs_review")
            profile["regions"] = []
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            manual_path = root / "manual_frame_review.json"
            manual_path.write_text(json.dumps({
                "schema_version": "1.0",
                "session_id": "session_001",
                "candidates": [{
                    "id": "manual_001",
                    "source": "manual_frame",
                    "status": "confirmed",
                    "timeMs": 1_000,
                }],
            }), encoding="utf-8")
            workspace = RegionProfileReviewWorkspace(
                profile_path=profile_path,
                evidence_root=root,
                manual_review_path=manual_path,
            )

            self.assertEqual(workspace.state()["summary"]["region_count"], 0)
            result = workspace.add_metric_region({})

            region = result["state"]["regions"][0]
            self.assertEqual(region["manual_sample_ids"], ["manual_001"])
            self.assertEqual(result["state"]["profile_status"], "needs_review")

    def test_scans_every_indexed_source_frame_and_only_region_crops(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for index in (1, 2):
                Image.new("RGB", (100, 100), (index * 30, 20, 10)).save(root / f"frame_{index:03d}.png")
            index_path = root / "frames_index.json"
            index_path.write_text(json.dumps({
                "session_id": "session_demo",
                "frames": [
                    {"index": 1, "seconds": 1.0, "timestamp": "00:00:01.000", "source_frame": "frame_001.png"},
                    {"index": 2, "seconds": 2.0, "timestamp": "00:00:02.000", "source_frame": "frame_002.png"},
                ],
            }), encoding="utf-8")
            profile_path = root / "ocr_region_profile.json"
            profile_path.write_text(json.dumps(self._profile(), ensure_ascii=False), encoding="utf-8")
            output = root / "output"

            result = scan_all_extracted_frames(
                RegionScanConfig(
                    index_json=index_path,
                    region_profile=profile_path,
                    output_dir=output,
                    save_crops=True,
                ),
                engine=FakeRegionEngine(),
            )

            events = json.loads(result.event_json.read_text(encoding="utf-8"))
            metrics = json.loads(result.metric_json.read_text(encoding="utf-8"))
            manifest = json.loads(result.manifest_json.read_text(encoding="utf-8"))
            self.assertEqual(result.frames_scanned, 2)
            self.assertEqual(result.region_scans, 6)
            self.assertEqual(events["scan_scope"], "all_extracted_frames")
            self.assertEqual(events["summary"]["raw_match_count"], 2)
            self.assertEqual(len(events["events"]), 1)
            self.assertEqual(events["events"][0]["event_name"], "伙伴副本")
            self.assertEqual(events["events"][0]["occurrence_frame_count"], 2)
            self.assertEqual(events["events"][0]["last_time_ms"], 2000)
            self.assertEqual(len(metrics["metrics"]), 2)
            self.assertEqual(
                [item["parsed_value"] for item in metrics["metrics"]],
                [100_000, 110_000],
            )
            self.assertEqual(manifest["counts"]["frames_scanned"], 2)
            self.assertEqual(manifest["counts"]["region_scans"], 6)
            serialized = json.dumps({"events": events, "metrics": metrics}, ensure_ascii=False)
            self.assertNotIn(str(root), serialized)

    def test_background_scan_job_reports_progress_and_result(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for index in (1, 2):
                Image.new("RGB", (100, 100), (index * 30, 20, 10)).save(root / f"frame_{index:03d}.png")
            index_path = root / "frames_index.json"
            index_path.write_text(json.dumps({
                "session_id": "session_demo",
                "frames": [
                    {"index": 1, "seconds": 1.0, "source_frame": "frame_001.png"},
                    {"index": 2, "seconds": 2.0, "source_frame": "frame_002.png"},
                ],
            }), encoding="utf-8")
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(self._profile(), ensure_ascii=False), encoding="utf-8")
            job = RegionScanJob(
                RegionScanConfig(
                    index_json=index_path,
                    region_profile=profile_path,
                    output_dir=root / "output",
                    save_crops=True,
                ),
                engine=FakeRegionEngine(),
            )
            started = job.start()
            self.assertEqual(started["status"], "running")
            completed = job.wait(5)
            self.assertEqual(completed["status"], "complete")
            self.assertEqual(completed["done"], 2)
            self.assertEqual(completed["result"]["region_scans"], 6)
            self.assertEqual(completed["result"]["metric_count"], 2)

    def test_stable_metric_collapses_across_long_observation_gaps(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for index in (1, 2):
                Image.new("RGB", (100, 100), "white").save(root / f"frame_{index:03d}.png")
            index_path = root / "frames_index.json"
            index_path.write_text(json.dumps({
                "session_id": "session_demo",
                "frames": [
                    {"index": 1, "seconds": 1.0, "source_frame": "frame_001.png"},
                    {"index": 2, "seconds": 601.0, "source_frame": "frame_002.png"},
                ],
            }), encoding="utf-8")
            profile = self._profile()
            profile["regions"] = profile["regions"][:1]
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

            result = scan_all_extracted_frames(
                RegionScanConfig(index_json=index_path, region_profile=profile_path, output_dir=root / "output"),
                engine=FakeStableMetricEngine(),
            )

            metrics = json.loads(result.metric_json.read_text(encoding="utf-8"))["metrics"]
            self.assertEqual(len(metrics), 1)
            self.assertEqual(metrics[0]["occurrence_frame_count"], 2)
            self.assertEqual(metrics[0]["last_time_ms"], 601_000)

    def test_rejects_unreviewed_profile(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (100, 100)).save(root / "frame.png")
            (root / "index.json").write_text(json.dumps({
                "frames": [{"index": 1, "seconds": 0, "source_frame": "frame.png"}],
            }), encoding="utf-8")
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(self._profile(status="needs_review"), ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(RegionProfileError):
                scan_all_extracted_frames(
                    RegionScanConfig(
                        index_json=root / "index.json",
                        region_profile=profile_path,
                        output_dir=root / "output",
                    ),
                    engine=FakeRegionEngine(),
                )

    def test_region_review_workspace_promotes_only_human_confirmed_profile(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (100, 100)).save(root / "frame_001.png")
            profile = self._profile(status="needs_review")
            profile["regions"] = profile["regions"][:1]
            profile["regions"][0]["sample_evidence"] = ["frame_001.png"]
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            workspace = RegionProfileReviewWorkspace(profile_path=profile_path, evidence_root=root)
            state = workspace.state()
            self.assertEqual(state["summary"]["needs_review"], 1)
            self.assertTrue(state["regions"][0]["source_url"])
            state = workspace.save_region({
                "region_id": "roi_power",
                "decision": "confirmed",
                "reviewer": "tester",
                "enabled": True,
                "region_kind": "metric",
                "rect_normalized": [0, 0, 0.5, 0.5],
                "scene_hint": "主界面战力",
                "metric_key": "combat_power",
                "parser": "numeric_cn",
            })
            self.assertEqual(state["profile_status"], "complete")
            saved = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["review"]["reviewer"], "tester")
            self.assertEqual(saved["regions"][0]["status"], "confirmed")

    def test_region_review_workspace_adds_pending_metric_region(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (100, 100)).save(root / "frame_001.png")
            profile = self._profile(status="complete")
            profile["regions"] = profile["regions"][:1]
            profile["regions"][0]["sample_evidence"] = ["frame_001.png"]
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            workspace = RegionProfileReviewWorkspace(profile_path=profile_path, evidence_root=root)
            result = workspace.add_metric_region({"sample_region_id": "roi_power"})
            self.assertEqual(result["region_id"], "roi_metric_custom_001")
            created = result["state"]["regions"][-1]
            self.assertEqual(created["status"], "needs_review")
            self.assertEqual(created["metric_key"], "unknown")
            self.assertEqual(created["parser"], "text")
            self.assertEqual(created["sample_evidence"], ["frame_001.png"])
            self.assertEqual(result["state"]["profile_status"], "needs_review")

    def test_region_workspace_uses_manual_samples_and_suggests_metric(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            evidence.mkdir()
            Image.new("RGB", (100, 100), "white").save(evidence / "frame_001.png")
            profile = self._profile(status="needs_review")
            profile["regions"] = profile["regions"][:1]
            profile["regions"][0]["sample_evidence"] = ["frame_001.png"]
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            manual_path = root / "manual_frame_review.json"
            manual_path.write_text(json.dumps({
                "schema_version": "1.0",
                "session_id": "demo",
                "updated_at": "2026-07-21T00:00:00+08:00",
                "candidates": [{
                    "id": "manual_001", "title": "战力画面", "status": "confirmed",
                    "source": "manual_frame", "timeMs": 1000,
                }],
            }, ensure_ascii=False), encoding="utf-8")
            cache = root / "manual_cache"
            cache.mkdir()
            Image.new("RGB", (100, 100), "white").save(cache / "manual_001_0000001000.jpg")
            video = root / "recording.mp4"
            video.write_bytes(b"video")
            workspace = RegionProfileReviewWorkspace(
                profile_path=profile_path,
                evidence_root=evidence,
                manual_review_path=manual_path,
                video_path=video,
                manual_cache_dir=cache,
                ocr_engine=FakeSuggestionEngine(),
            )
            state = workspace.state()
            self.assertEqual(state["manual_samples"][0]["id"], "manual_001")
            suggestion = workspace.suggest_metric({
                "region_id": "roi_power",
                "rect_normalized": [0, 0, 0.5, 0.5],
                "manual_sample_ids": ["manual_001"],
            })
            self.assertEqual(suggestion["metric_key"], "combat_power")
            self.assertEqual(suggestion["parser"], "numeric_cn")
            self.assertEqual(suggestion["ocr_texts"], ["战力 11.04万"])

    def test_scan_job_restores_a_completed_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "event_observations_v2.json").write_text("{}", encoding="utf-8")
            (output / "metric_observations_v2.json").write_text("{}", encoding="utf-8")
            (output / "region_scan_manifest.json").write_text(json.dumps({
                "counts": {
                    "frames_total": 12,
                    "frames_scanned": 12,
                    "region_scans": 36,
                    "event_observations": 2,
                    "metric_observations": 7,
                },
                "timing": {"total_elapsed_seconds": 3.5},
                "outputs": ["event_observations_v2.json", "metric_observations_v2.json"],
            }), encoding="utf-8")
            job = RegionScanJob(RegionScanConfig(
                index_json=root / "index.json",
                region_profile=root / "profile.json",
                output_dir=output,
            ))
            state = job.state()
            self.assertEqual(state["status"], "complete")
            self.assertEqual(state["done"], 12)
            self.assertEqual(state["result"]["metric_count"], 7)
            self.assertEqual(state["result"]["elapsed_seconds"], 3.5)

    def test_metric_parsers(self):
        value, fields, unit = parse_metric_text("战力：11.04万", parser="numeric_cn")
        self.assertEqual(value, 110_400)
        self.assertEqual(fields["display_unit"], "万")
        self.assertEqual(unit, "")
        value, _fields, _unit = parse_metric_text(
            "战力：11.04万",
            parser="numeric_cn",
            metric_key="combat_power",
        )
        self.assertEqual(value, 110_400)
        value, _fields, _unit = parse_metric_text(
            "诚力164.73万",
            parser="numeric_cn",
            metric_key="combat_power",
        )
        self.assertEqual(value, 1_647_300)
        for health_text in ("30.55万/30.55万", "64.07万/129万", "189万/189万"):
            value, fields, unit = parse_metric_text(
                health_text,
                parser="numeric_cn",
                metric_key="combat_power",
            )
            self.assertIsNone(value)
            self.assertEqual(fields, {})
            self.assertEqual(unit, "")
        value, fields, _unit = parse_metric_text("10转805级", parser="level_rebirth")
        self.assertEqual(value, "10转805级")
        self.assertEqual(fields, {"level": 805, "rebirth": 10})

    def test_legacy_layout_converts_to_reviewable_draft(self):
        legacy = {
            "schema_version": "1.0",
            "session_id": "demo",
            "video": {"width": 460, "height": 866},
            "regions": [{
                "region_id": "roi_power",
                "role": "combat_power",
                "label": "战力固定区域",
                "box_norm": [0.1, 0.1, 0.3, 0.2],
                "sample_texts": ["战力11.04万"],
                "source_frame": "frames/frame.jpg",
                "preview": "previews/roi.jpg",
                "enabled": True,
            }],
        }
        result = convert_legacy_layout_profile(legacy, game_id="demo", game_name="测试游戏")
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["scan_scope"], "all_extracted_frames")
        self.assertEqual(result["regions"][0]["metric_key"], "combat_power")
        self.assertEqual(result["regions"][0]["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
