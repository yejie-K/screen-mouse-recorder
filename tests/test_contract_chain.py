from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis import (  # noqa: E402
    build_event_review_bundle,
    build_semantic_input,
    migrate_semantic_input_v1,
    initialize_journey_workspace,
    generate_final_product,
    generate_preview_product,
    sync_journey_workspace,
    refresh_journey_workspace,
    validate_final_gate,
)
from screen_mouse_recorder.journey_analysis.rules import load_rule_file  # noqa: E402


class ContractChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy = load_rule_file(ROOT / "rules" / "gameplay_taxonomy_v0.1.json")
        cls.emotion = load_rule_file(ROOT / "rules" / "emotion_rules_v0.1.json")

    @staticmethod
    def _event_candidates() -> dict:
        return {
            "schema_version": "2.0",
            "task_id": "JOURNEY_EVENT_OBSERVATIONS_V2",
            "source_fingerprint": "region-scan-fingerprint",
            "status": "needs_review",
            "scan_scope": "all_extracted_frames",
            "session": {"session_id": "session_001"},
            "summary": {"observation_count": 1, "pending": 1, "confirmed": 0, "excluded": 0},
            "events": [{
                "observation_id": "event_partner_000001",
                "session_id": "session_001",
                "time_ms": 80_000,
                "timestamp": "00:01:20.000",
                "source": "automatic",
                "evidence": {
                    "source_image": "frame_000001.jpg",
                    "frame_index": 1,
                    "region_ids": ["roi_partner"],
                    "crop_images": ["region_crops/partner.jpg"],
                },
                "event_name": "伙伴副本",
                "ocr_text": "新功能开启 伙伴副本",
                "confidence": 0.95,
                "mode_tag": "PVE",
                "event_tag": "新副本",
                "region_group_id": "partner",
                "review": {"status": "pending", "reviewer": "", "reviewed_at": "", "note": ""},
            }],
            "compatibility": {},
        }

    def test_event_v2_builds_one_linked_review_bundle(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "event_observations_v2.json"
            original = self._event_candidates()
            source.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            original_bytes = source.read_bytes()
            output = root / "event_review"
            manifest = build_event_review_bundle(
                source,
                output,
                taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
                emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
            )
            semantic_input = json.loads((output / "journey_semantic_input.json").read_text(encoding="utf-8"))
            semantic_output = json.loads((output / "journey_semantic_output.json").read_text(encoding="utf-8"))
            review = json.loads((output / "journey_semantic_review.json").read_text(encoding="utf-8"))
            confirmed = json.loads((output / "confirmed_semantic_events.json").read_text(encoding="utf-8"))
            self.assertEqual(semantic_input["schema_version"], "1.1")
            self.assertEqual(semantic_output["schema_version"], "1.0")
            self.assertEqual(review["schema_version"], "1.0")
            self.assertEqual(confirmed["status"], "needs_review")
            self.assertEqual(
                semantic_output["event_annotations"][0]["tags"],
                ["PVE", "新副本"],
            )
            self.assertEqual(manifest["upstream"]["source_fingerprint"], original["source_fingerprint"])
            self.assertEqual(
                manifest["review_source_fingerprint"],
                semantic_input["source_fingerprint"],
            )
            self.assertEqual(source.read_bytes(), original_bytes)

    def test_semantic_input_v1_migration_is_explicit_and_stable(self) -> None:
        payload = {
            "schema_version": "1.0",
            "task_id": "JOURNEY_SEMANTIC_V1",
            "source_fingerprint": "a" * 64,
            "rule_versions": {"gameplay": "g", "emotion": "e"},
            "session": {"session_id": "demo", "confirmed_at": "", "duration_ms": 80_000, "event_count": 1, "event_type_counts": {}},
            "events": [{
                "event_id": "evt_001",
                "session_id": "demo",
                "time_ms": 80_000,
                "timestamp": "00:01:20.000",
                "event_type": "new_feature_unlocked",
                "event_name": "伙伴副本",
                "ocr_excerpt": "",
                "evidence": {"source_image": "", "review_image": "", "contact_sheet": "", "sheet_row": None, "sheet_col": None},
                "deterministic_hints": {"matched_gameplay_rule_ids": [], "classification": {}, "suggested_emotion_rule_ids": []},
            }],
        }
        migrated = migrate_semantic_input_v1(payload)
        self.assertEqual(migrated["schema_version"], "1.1")
        self.assertEqual(migrated["events"][0]["video_time_ms"], 80_000)
        self.assertEqual(migrated["events"][0]["global_time_ms"], 80_000)
        self.assertEqual(migrated["session"]["virtual_day_minutes"], 60)
        self.assertEqual(payload["schema_version"], "1.0")

    def test_final_product_input_filters_non_confirmed_events_and_keeps_reviewed_labels(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "confirmed_semantic_events.json"
            payload = {
                "task_id": "JOURNEY_CONFIRMED_SEMANTIC_V1",
                "confirmed_at": "2026-07-22T00:00:00+08:00",
                "events": [
                    {
                        "event_id": "evt_confirmed",
                        "time_ms": 1_000,
                        "event_type": "new_feature_unlocked",
                        "event_name": "伙伴副本",
                        "ocr_excerpt": "伙伴副本",
                        "evidence": {"source_image": "frame.jpg"},
                        "semantic": {
                            "mode_tag": "PVE",
                            "event_tag": "新副本",
                            "event_category": "玩法开放",
                            "object_scope": ["伙伴"],
                            "interaction_mode": ["PVE"],
                            "gameplay_form": ["副本"],
                            "rhythm_category": ["PVE"],
                            "matched_gameplay_rule_ids": ["GAME-PVE-DUNGEON"],
                        },
                        "semantic_review": {"status": "confirmed"},
                    },
                    {
                        "event_id": "evt_excluded",
                        "time_ms": 2_000,
                        "event_type": "new_feature_unlocked",
                        "event_name": "无效项",
                        "semantic_review": {"status": "excluded"},
                    },
                ],
            }
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = build_semantic_input(
                source,
                payload,
                self.taxonomy,
                self.emotion,
                session_id="demo",
            )
            self.assertEqual([event["event_id"] for event in result["events"]], ["evt_confirmed"])
            classification = result["events"][0]["deterministic_hints"]["classification"]
            self.assertEqual(classification["mode_tag"], "PVE")
            self.assertEqual(classification["event_tag"], "新副本")

    def test_repository_contract_schema_versions_are_unambiguous(self) -> None:
        expected = {
            "manual_frame_review.schema.json": "1.0",
            "selected_ocr_tiles.schema.json": "1.0",
            "ocr_region_profile.schema.json": "1.1",
            "journey_event_observations.schema.json": "2.0",
            "journey_metric_observations.schema.json": "2.0",
            "journey_semantic_input.schema.json": "1.1",
            "journey_semantic_output.schema.json": "1.0",
            "journey_semantic_review.schema.json": "1.0",
            "journey_metric_review.schema.json": "1.0",
            "confirmed_semantic_events.schema.json": "1.0",
            "event_review_manifest.schema.json": "1.0",
            "journey_workspace.schema.json": "1.0",
            "journey_final_manifest.schema.json": "1.0",
            "journey_preview_manifest.schema.json": "1.0",
            "journey_run_preflight.schema.json": "1.0",
            "journey_run_prepare_report.schema.json": "1.0",
            "analysis_handoff.schema.json": "1.0",
        }
        schema_ids = set()
        for filename, version in expected.items():
            payload = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
            self.assertEqual(payload["properties"]["schema_version"]["const"], version, filename)
            self.assertNotIn(payload["$id"], schema_ids)
            schema_ids.add(payload["$id"])

    def test_new_workspace_creates_editable_region_draft_without_legacy_profile(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            session.mkdir()
            (session / "recording.mp4").write_bytes(b"video")
            (session / "session_meta.json").write_text(json.dumps({
                "schema_version": "1.0",
                "session_id": "session_001",
                "video": {"file": "recording.mp4", "width": 470, "height": 846},
            }), encoding="utf-8")
            Image.new("RGB", (100, 100), "white").save(session / "sheet.png")
            index = session / "index.json"
            index.write_text(json.dumps({
                "frames": [{
                    "index": 1,
                    "seconds": 1.0,
                    "sheet": "sheet.png",
                    "sheet_row": 1,
                    "sheet_col": 1,
                }],
            }), encoding="utf-8")

            workspace = root / "workspace"
            manifest = initialize_journey_workspace(
                session,
                index,
                workspace,
                game_id="demo",
                game_name="测试游戏",
            )

            self.assertEqual(manifest["artifacts"]["region_profile"], "region/ocr_region_profile.json")
            self.assertEqual(manifest["stages"]["region_profile"]["status"], "needs_review")
            profile = json.loads((workspace / "region" / "ocr_region_profile.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["source_frame"], {"width": 470, "height": 846})
            self.assertEqual(profile["regions"], [])

    def test_new_workspace_links_one_session_without_legacy_event_data(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "sessions" / "session_001"
            export = session / "analysis_output"
            export.mkdir(parents=True)
            (session / "recording.mp4").write_bytes(b"video")
            (session / "session_meta.json").write_text(json.dumps({
                "schema_version": "1.0",
                "session_id": "session_001",
                "video": {"file": "recording.mp4", "segments": [{"end_video_ms": 5_000}]},
            }), encoding="utf-8")
            Image.new("RGB", (100, 100), "white").save(export / "sheet_001.png")
            index = export / "click_keyframes_index.json"
            index.write_text(json.dumps({
                "frames": [{
                    "index": 1,
                    "event_id": "evt_001",
                    "seconds": 1.25,
                    "timestamp": "00:00:01.250",
                    "sheet": "sheet_001.png",
                    "sheet_row": 1,
                    "sheet_col": 1,
                }],
            }), encoding="utf-8")
            profile = root / "profile.json"
            profile.write_text(json.dumps({
                "schema_version": "1.1",
                "game_id": "demo",
                "game_name": "测试游戏",
                "status": "complete",
                "scan_scope": "all_extracted_frames",
                "source_frame": {"width": 100, "height": 100},
                "regions": [{
                    "region_id": "metric_001",
                    "region_kind": "metric",
                    "rect_normalized": [0.1, 0.1, 0.5, 0.2],
                    "scene_hint": "等级",
                    "sample_texts": ["1级"],
                    "sample_evidence": [],
                    "enabled": True,
                    "status": "confirmed",
                    "metric_key": "level",
                    "parser": "integer",
                }],
                "review": {"reviewer": "tester", "reviewed_at": "2026-07-22T00:00:00+08:00"},
            }), encoding="utf-8")
            workspace = root / "workspace"
            manifest = initialize_journey_workspace(
                session, index, workspace,
                game_id="demo", game_name="测试游戏", region_profile=profile,
            )
            self.assertEqual(manifest["session"]["frame_count"], 1)
            self.assertEqual(manifest["stages"]["preview_product"]["status"], "blocked")
            runtime = json.loads((workspace / "runtime" / "review_session.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["sourceIndex"], "keyframes_index.json")
            self.assertEqual(runtime["videoFile"], "recording.mp4")

            manual = {
                "schema_version": "1.0",
                "session_id": "session_001",
                "updated_at": "2026-07-22T00:00:00+08:00",
                "candidates": [{
                    "id": "manual_001",
                    "title": "伙伴",
                    "eventKind": "new_feature",
                    "status": "confirmed",
                    "timeMs": 1_250,
                    "timecode": "00:00:01.250",
                    "source": "manual_frame",
                    "confidence": 1,
                    "ocrText": "新功能开启",
                    "evidenceFile": "sheet_001.png · tile_1",
                    "eventId": "evt_001",
                    "note": "",
                    "contactSheet": "sheet_001.png",
                    "contactSheetTileId": "tile_1",
                    "sheetRow": 1,
                    "sheetColumn": 1,
                }],
            }
            manual["candidates"].append({
                **manual["candidates"][0],
                "id": "manual_metric_001",
                "title": "10级",
                "eventKind": "growth",
                "timeMs": 2_000,
                "timecode": "00:00:02.000",
                "eventId": "evt_002",
            })
            (workspace / "review" / "manual_frame_review.json").write_text(json.dumps(manual), encoding="utf-8")
            fingerprint = __import__("hashlib").sha256(
                (workspace / "runtime" / "keyframes_index.json").read_bytes()
                + (workspace / "region" / "ocr_region_profile.json").read_bytes()
            ).hexdigest()
            event_candidates = self._event_candidates()
            event_candidates.update({
                "source_fingerprint": fingerprint,
                "session": {"session_id": "session_001"},
                "summary": {"observation_count": 0, "pending": 0, "confirmed": 0, "excluded": 0},
                "events": [],
                "status": "complete",
            })
            metric_candidates = {
                "schema_version": "2.0",
                "task_id": "JOURNEY_METRIC_OBSERVATIONS_V2",
                "source_fingerprint": fingerprint,
                "status": "complete",
                "scan_scope": "all_extracted_frames",
                "session": {"session_id": "session_001"},
                "summary": {"observation_count": 0, "pending": 0, "confirmed": 0, "excluded": 0},
                "metrics": [],
                "compatibility": {},
            }
            (workspace / "scan" / "event_observations_v2.json").write_text(json.dumps(event_candidates), encoding="utf-8")
            (workspace / "scan" / "metric_observations_v2.json").write_text(json.dumps(metric_candidates), encoding="utf-8")
            synced = sync_journey_workspace(
                workspace,
                taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
                emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
            )
            self.assertEqual(synced["stages"]["event_review"]["event_count"], 1)
            combined = json.loads((workspace / "event_review" / "event_observations_v2.json").read_text(encoding="utf-8"))
            self.assertEqual(combined["summary"]["manual_count"], 1)
            self.assertEqual(combined["summary"]["manual_metric_sample_count"], 1)
            self.assertEqual(combined["summary"]["automatic_count"], 0)
            self.assertEqual(combined["events"][0]["source"], "manual")
            review_bundle = json.loads((workspace / "event_review" / "event_review_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(review_bundle["manual_confirmed_count"], 1)
            self.assertEqual(review_bundle["review_candidate_count"], 0)
            confirmed_path = workspace / "event_review" / "confirmed_semantic_events.json"
            confirmed = json.loads(confirmed_path.read_text(encoding="utf-8"))
            self.assertEqual(confirmed["status"], "complete")
            self.assertEqual(confirmed["summary"]["confirmed_count"], 1)
            self.assertEqual(confirmed["events"][0]["source"], "manual")
            validate_final_gate(workspace)
            preview = generate_preview_product(workspace)
            self.assertEqual(preview["status"], "draft")
            self.assertTrue((workspace / "preview" / "游戏历程拆解候选预览.xlsx").is_file())
            self.assertEqual(len(preview["outputs"]["charts"]), 3)
            self.assertTrue((workspace / "preview" / "charts" / "玩法系统开放节奏_候选预览.agent_spec.json").is_file())
            self.assertIn("generate_journey_preview.py", (workspace / "preview" / "charts" / "玩法系统开放节奏_候选预览.agent_report.md").read_text(encoding="utf-8"))
            semantic_review_path = workspace / "event_review" / "journey_semantic_review.json"
            review_before = semantic_review_path.read_bytes()
            manual["updated_at"] = "2026-07-22T01:00:00+08:00"
            (workspace / "review" / "manual_frame_review.json").write_text(json.dumps(manual), encoding="utf-8")
            resynced = sync_journey_workspace(
                workspace,
                taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
                emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
            )
            self.assertEqual(resynced["stages"]["event_review"]["status"], "complete")
            self.assertEqual(semantic_review_path.read_bytes(), review_before)
            final = generate_final_product(
                workspace,
                taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
                emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
            )
            self.assertEqual(final["status"], "complete")
            self.assertTrue((workspace / "final" / "游戏历程拆解结果.xlsx").is_file())
            self.assertEqual(len(final["outputs"]["charts"]), 3)
            self.assertTrue((workspace / "final" / "charts" / "玩法系统开放节奏.agent_spec.json").is_file())
            self.assertIn("generate_journey_final.py", (workspace / "final" / "charts" / "玩法系统开放节奏.agent_report.md").read_text(encoding="utf-8"))
            profile_payload = json.loads((workspace / "region" / "ocr_region_profile.json").read_text(encoding="utf-8"))
            profile_payload["regions"][0]["rect_normalized"] = [0.2, 0.1, 0.5, 0.2]
            (workspace / "region" / "ocr_region_profile.json").write_text(json.dumps(profile_payload), encoding="utf-8")
            stale = refresh_journey_workspace(workspace)
            self.assertEqual(stale["stages"]["region_scan"]["status"], "stale")
            self.assertEqual(stale["stages"]["event_review"]["status"], "stale")
            self.assertEqual(stale["stages"]["metric_review"]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
