from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.charts import render_emotion_timeline_draft, render_open_timeline
from screen_mouse_recorder.journey_analysis.handoff import build_open_timeline_agent_spec, render_open_timeline_agent_report
from screen_mouse_recorder.journey_analysis.game_profile import (
    find_game_term,
    new_game_profile,
    normalize_game_term,
    upsert_game_term,
)
from screen_mouse_recorder.journey_analysis.package import (
    JourneyPackageError,
    build_semantic_input,
    build_semantic_review_template,
    finalize_semantic_review,
    validate_semantic_output,
)
from screen_mouse_recorder.journey_analysis.rules import classify_event, load_rule_file, score_emotion
from screen_mouse_recorder.journey_analysis.review_workspace import SemanticReviewWorkspace
from screen_mouse_recorder.journey_analysis.tagging import (
    infer_event_labels,
    normalize_tags,
    observation_lane,
    split_confirmed_v1_to_parallel_v2,
    tags_from_annotation,
)


class JourneyAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy = load_rule_file(ROOT / "rules" / "gameplay_taxonomy_v0.1.json")
        cls.emotion = load_rule_file(ROOT / "rules" / "emotion_rules_v0.1.json")

    def test_partner_dungeon_gets_multiple_dimensions(self):
        result = classify_event(
            {"event_type": "new_feature_unlocked", "event_name": "伙伴副本", "ocr_text": "伙伴副本 新功能开启"},
            self.taxonomy,
        )
        labels = result["classification"]
        self.assertEqual(labels["event_category"], "玩法开放")
        self.assertIn("伙伴", labels["object_scope"])
        self.assertIn("PVE", labels["interaction_mode"])
        self.assertIn("副本", labels["gameplay_form"])
        self.assertIn("PVE", labels["rhythm_category"])
        self.assertIn("GAME-SCOPE-PARTNER", result["matched_gameplay_rule_ids"])
        self.assertIn("GAME-PVE-DUNGEON", result["matched_gameplay_rule_ids"])

    def test_game_profile_is_per_game_and_uses_normalized_exact_match(self):
        profile = new_game_profile("qingyun", "青云诀之伏魔")
        annotation = {
            "event_category": "玩法开放",
            "object_scope": ["伙伴"],
            "interaction_mode": ["PVE"],
            "gameplay_form": ["副本"],
            "rhythm_category": ["PVE"],
        }
        profile = upsert_game_term(
            profile,
            term="伙伴·副本",
            annotation=annotation,
            event_id="evt_001",
            reviewer="tester",
            reviewed_at="2026-07-21T10:00:00+08:00",
        )
        self.assertEqual(normalize_game_term("伙伴 副本"), "伙伴副本")
        match = find_game_term(profile, "伙伴副本")
        self.assertIsNotNone(match)
        self.assertEqual(match["mapping"]["gameplay_form"], ["副本"])
        self.assertEqual(match["mapping"]["mode_tag"], "PVE")
        self.assertEqual(match["mapping"]["event_tag"], "新副本")
        self.assertEqual(match["mapping"]["tags"], ["PVE", "新副本"])
        self.assertIsNone(find_game_term(profile, "其他游戏伙伴系统"))

    def test_legacy_dimensions_collapse_to_two_event_labels(self):
        legacy = {
            "object_scope": ["伙伴"],
            "interaction_mode": ["PVE"],
            "gameplay_form": ["副本"],
            "rhythm_category": ["PVE"],
        }
        self.assertEqual(
            tags_from_annotation(legacy, event_type="new_feature_unlocked"),
            ["PVE", "新副本"],
        )
        self.assertEqual(
            infer_event_labels({**legacy, "mode_tag": "系统", "event_tag": "新养成系统"}),
            ("系统", "新养成系统"),
        )
        self.assertEqual(tags_from_annotation({}, event_type="level_snapshot"), [])
        self.assertEqual(observation_lane("combat_power_snapshot"), "metric")
        self.assertEqual(
            normalize_tags(["pve", " PVE ", "其他", "养成系统", "养成"]),
            ["PVE", "新养成系统"],
        )

    def test_confirmed_v1_splits_event_and_metric_lanes(self):
        payload = {
            "task_id": "JOURNEY_CONFIRMED_SEMANTIC_V1",
            "source_fingerprint": "a" * 64,
            "session": {"session_id": "demo"},
            "events": [
                {
                    "event_id": "evt_feature",
                    "event_type": "new_feature_unlocked",
                    "event_name": "伙伴副本",
                    "time_ms": 500,
                    "timestamp": "00:00:00.500",
                    "evidence": {"source_image": "feature.jpg"},
                    "semantic": {"interaction_mode": ["PVE"], "gameplay_form": ["副本"]},
                    "semantic_review": {"status": "confirmed", "reviewer": "tester", "reviewed_at": "now"},
                },
                {
                    "event_id": "evt_metric",
                    "event_type": "level_snapshot",
                    "event_name": "10转680级",
                    "time_ms": 1_000,
                    "timestamp": "00:00:01.000",
                    "evidence": {"source_image": "metric.jpg"},
                    "semantic": {},
                    "semantic_review": {"status": "excluded", "reviewer": "tester", "reviewed_at": "now"},
                },
            ],
        }
        events, metrics = split_confirmed_v1_to_parallel_v2(payload)
        self.assertEqual(events["summary"]["pending"], 1)
        self.assertEqual(events["events"][0]["mode_tag"], "PVE")
        self.assertEqual(events["events"][0]["event_tag"], "新副本")
        self.assertEqual(events["events"][0]["review"]["legacy_event_review_status"], "confirmed")
        self.assertEqual(metrics["summary"]["pending"], 1)
        self.assertEqual(metrics["metrics"][0]["metric_key"], "level_rebirth")
        self.assertEqual(metrics["metrics"][0]["review"]["legacy_event_review_status"], "excluded")
        self.assertEqual(metrics["metrics"][0]["evidence"]["source_image"], "metric.jpg")

    def test_emotion_scoring_repeat_and_override(self):
        first = score_emotion(["EMO-PLAY-001"], self.emotion)
        repeated = score_emotion(
            ["EMO-PLAY-001"], self.emotion, repeat_index=2, has_new_value=False
        )
        override = score_emotion(
            ["EMO-PLAY-003"], self.emotion, creative_high_value=True
        )
        self.assertEqual(first["score"], 2)
        self.assertEqual(repeated["score"], 1)
        self.assertEqual(override["score"], 3)

    def test_system_unlock_does_not_get_gameplay_first_score(self):
        event = {"event_type": "new_feature_unlocked", "event_name": "宝石", "ocr_text": "宝石 新功能开启"}
        hints = classify_event(event, self.taxonomy)
        from screen_mouse_recorder.journey_analysis.rules import suggest_emotion_rule_ids

        self.assertEqual(
            suggest_emotion_rule_ids(event, hints["classification"]),
            ["EMO-PLAY-003"],
        )

    def test_semantic_input_removes_absolute_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "confirmed.json"
            payload = {
                "confirmed_at": "2026-07-20T10:00:00+08:00",
                "events": [{
                    "event_id": "evt_001",
                    "time_ms": 80000,
                    "timestamp": "00:01:20.000",
                    "event_type": "new_feature_unlocked",
                    "event_name": "伙伴副本",
                    "ocr_text": "伙伴副本 新功能开启",
                    "source_image": "D:/private/source.jpg",
                    "review_image": "D:/private/review.jpg",
                    "contact_sheet": "click_sheet.png",
                    "sheet_row": 1,
                    "sheet_col": 2,
                }],
            }
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = build_semantic_input(
                source, payload, self.taxonomy, self.emotion, session_id="demo"
            )
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertNotIn("D:/private", serialized)
            self.assertEqual(result["events"][0]["evidence"]["source_image"], "source.jpg")
            self.assertEqual(result["schema_version"], "1.1")
            self.assertEqual(result["events"][0]["play_day_index"], 1)
            self.assertEqual(result["events"][0]["day_time_ms"], 80000)

    def test_sixty_minutes_starts_a_new_virtual_day(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "confirmed.json"
            payload = {
                "events": [
                    {"event_id": "evt_001", "time_ms": 1000, "global_time_ms": 3_599_999, "event_type": "new_feature_unlocked", "event_name": "伙伴", "ocr_text": ""},
                    {"event_id": "evt_002", "time_ms": 2000, "global_time_ms": 3_600_000, "event_type": "new_feature_unlocked", "event_name": "副本", "ocr_text": ""},
                ]
            }
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = build_semantic_input(
                source, payload, self.taxonomy, self.emotion, session_id="demo", total_play_time_ms=7_200_000
            )
            self.assertEqual(result["session"]["virtual_day_count"], 2)
            self.assertEqual(result["events"][0]["play_day_index"], 1)
            self.assertEqual(result["events"][0]["day_time_ms"], 3_599_999)
            self.assertEqual(result["events"][1]["play_day_index"], 2)
            self.assertEqual(result["events"][1]["day_time_ms"], 0)

    def _open_event(self, event_id: str, global_time_ms: int, name: str = "副本"):
        return {
            "event_id": event_id,
            "time_ms": global_time_ms,
            "global_time_ms": global_time_ms,
            "timestamp": "00:00:00.000",
            "event_type": "new_feature_unlocked",
            "event_name": name,
            "ocr_excerpt": "",
            "deterministic_hints": classify_event(
                {"event_type": "new_feature_unlocked", "event_name": name, "ocr_text": ""},
                self.taxonomy,
            ),
        }

    def test_one_hundred_thirty_minutes_produces_three_virtual_days(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "confirmed.json"
            payload = {
                "events": [
                    {"event_id": "evt_001", "time_ms": 1_000, "event_type": "new_feature_unlocked", "event_name": "副本", "ocr_text": ""},
                ]
            }
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = build_semantic_input(
                source,
                payload,
                self.taxonomy,
                self.emotion,
                session_id="demo",
                total_play_time_ms=130 * 60_000,
            )
            self.assertEqual(result["session"]["virtual_day_count"], 3)

    def test_multiday_chart_groups_days_and_expands_dense_lanes(self):
        minute = 60_000
        dense_events = [
            self._open_event(f"evt_{index:03d}", index * 2_000, f"功能{index}")
            for index in range(1, 9)
        ]
        semantic_input = {
            "session": {
                "duration_ms": 130 * minute,
                "total_play_time_ms": 130 * minute,
                "virtual_day_count": 3,
            },
            "events": dense_events + [
                self._open_event("evt_101", 65 * minute, "竞技"),
                self._open_event("evt_102", 125 * minute, "帮会"),
            ],
        }
        with TemporaryDirectory() as directory:
            output = Path(directory) / "timeline.png"
            report = render_open_timeline(semantic_input, output)
            self.assertEqual(report["layout_mode"], "continuous_multi_day")
            self.assertEqual(report["cycle_summary_side"], "above")
            self.assertEqual(report["event_block_side"], "below")
            self.assertEqual(report["connector_mode"], "first_row_two_segment_column_chain")
            self.assertEqual(report["day_count"], 3)
            self.assertEqual(report["page_count"], 1)
            self.assertGreater(report["lane_count"], 1)
            self.assertEqual(report["nodes"][0]["matrix_column"], 1)
            self.assertEqual(report["nodes"][0]["matrix_row"], 1)
            self.assertEqual(report["nodes"][1]["matrix_column"], 1)
            self.assertEqual(report["nodes"][1]["matrix_row"], 2)
            self.assertEqual(report["day_summaries"][2]["duration_ms"], 10 * minute)
            self.assertTrue(output.is_file())

    def test_eight_virtual_days_stay_on_one_continuous_timeline(self):
        minute = 60_000
        semantic_input = {
            "session": {
                "duration_ms": 8 * 60 * minute,
                "total_play_time_ms": 8 * 60 * minute,
                "virtual_day_count": 8,
            },
            "events": [self._open_event("evt_001", 1_000)],
        }
        with TemporaryDirectory() as directory:
            output = Path(directory) / "timeline.png"
            report = render_open_timeline(semantic_input, output)
            self.assertEqual(report["layout_mode"], "continuous_multi_day")
            self.assertEqual(report["day_count"], 8)
            self.assertEqual(report["page_count"], 1)
            self.assertEqual(report["outputs"], ["timeline.png"])
            self.assertFalse(output.with_name("timeline_part02.png").exists())

    def test_open_timeline_renders_confirmed_features(self):
        semantic_input = {
            "source_fingerprint": "a" * 64,
            "session": {
                "session_id": "demo",
                "duration_ms": 300000,
                "total_play_time_ms": 300000,
                "virtual_day_count": 1,
            },
            "events": [
                {
                    "event_id": "evt_001", "time_ms": 80000, "timestamp": "00:01:20.000",
                    "event_type": "new_feature_unlocked", "event_name": "伙伴副本",
                    "deterministic_hints": classify_event(
                        {"event_type": "new_feature_unlocked", "event_name": "伙伴副本", "ocr_text": ""},
                        self.taxonomy,
                    ),
                },
                {
                    "event_id": "evt_002", "time_ms": 90000, "timestamp": "00:01:30.000",
                    "event_type": "new_skill_unlocked", "event_name": "剑气",
                    "deterministic_hints": classify_event(
                        {"event_type": "new_skill_unlocked", "event_name": "剑气", "ocr_text": ""},
                        self.taxonomy,
                    ),
                },
            ],
        }
        with TemporaryDirectory() as directory:
            output = Path(directory) / "timeline.png"
            report = render_open_timeline(semantic_input, output)
            self.assertEqual(report["event_count"], 1)
            self.assertEqual(report["layout_mode"], "single_session")
            self.assertEqual(report["event_block_side"], "below")
            self.assertEqual(report["connector_mode"], "first_row_two_segment_column_chain")
            self.assertEqual(report["nodes"][0]["matrix_row"], 1)
            self.assertEqual(report["nodes"][0]["matrix_column"], 1)
            self.assertEqual(report["outputs"], ["timeline.png"])
            self.assertEqual(report["nodes"][0]["block_type_candidate"], "副本")
            self.assertEqual(report["nodes"][0]["interaction_mode_candidate"], "PVE")
            self.assertTrue(output.is_file())
            spec = build_open_timeline_agent_spec(
                semantic_input,
                report,
                self.taxonomy,
                game_name="测试游戏",
            )
            markdown = render_open_timeline_agent_report(spec)
            self.assertEqual(spec["game"]["game_name"], "测试游戏")
            self.assertEqual(spec["drawing_inputs"]["events"][0]["visual_encoding"]["block_type"], "副本")
            self.assertIn("PVP", spec["classification_model"]["visual_border"]["colors"])
            self.assertIn("测试游戏", markdown)
            self.assertIn("伙伴副本", markdown)
            self.assertNotIn(str(Path(directory)), json.dumps(spec, ensure_ascii=False))
            with Image.open(output) as image:
                self.assertGreater(len(image.getcolors(maxcolors=image.width * image.height) or []), 3)

    def test_emotion_timeline_uses_rule_candidates_only(self):
        hint = classify_event(
            {"event_type": "new_feature_unlocked", "event_name": "伙伴副本", "ocr_text": ""},
            self.taxonomy,
        )
        hint["suggested_emotion_rule_ids"] = ["EMO-PLAY-001"]
        semantic_input = {
            "session": {"duration_ms": 300000},
            "events": [{
                "event_id": "evt_001", "time_ms": 80000, "timestamp": "00:01:20.000",
                "event_type": "new_feature_unlocked", "event_name": "伙伴副本",
                "deterministic_hints": hint,
            }],
        }
        with TemporaryDirectory() as directory:
            output = Path(directory) / "emotion.png"
            report = render_emotion_timeline_draft(semantic_input, self.emotion, output)
            self.assertEqual(report["nodes"][0]["emotion_score_candidate"], 2)
            self.assertTrue(output.is_file())

    def test_ai_output_cannot_confirm_or_override_rule_score(self):
        semantic_input = {
            "source_fingerprint": "a" * 64,
            "events": [{"event_id": "evt_001"}],
        }
        payload = {
            "schema_version": "1.0",
            "task_id": "JOURNEY_SEMANTIC_V1",
            "source_fingerprint": "a" * 64,
            "event_annotations": [{
                "event_id": "evt_001",
                "event_category": "玩法开放",
                "object_scope": ["伙伴"],
                "interaction_mode": ["PVE"],
                "gameplay_form": ["副本"],
                "rhythm_category": ["PVE"],
                "matched_gameplay_rule_ids": ["GAME-PVE-DUNGEON"],
                "matched_emotion_rule_ids": ["EMO-PLAY-001"],
                "repeat_index": 1,
                "has_new_value": True,
                "creative_high_value": False,
                "emotion_score_candidate": 3,
                "output_relations": [],
                "review_status": "confirmed",
            }],
        }
        errors = validate_semantic_output(payload, semantic_input, self.taxonomy, self.emotion)
        self.assertTrue(any("不能写成已确认" in error for error in errors))
        self.assertTrue(any("应由规则计算为 2" in error for error in errors))

    def test_human_review_is_required_to_create_confirmed_semantics(self):
        semantic_input = {
            "source_fingerprint": "a" * 64,
            "session": {"session_id": "demo", "event_count": 1},
            "events": [{
                "event_id": "evt_001",
                "event_name": "伙伴副本",
                "event_type": "new_feature_unlocked",
                "global_time_ms": 80_000,
                "evidence": {"source_image": "frame.jpg"},
            }],
        }
        ai_output = {
            "schema_version": "1.0",
            "task_id": "JOURNEY_SEMANTIC_V1",
            "source_fingerprint": "a" * 64,
            "event_annotations": [{
                "event_id": "evt_001",
                "event_category": "玩法开放",
                "object_scope": ["伙伴"],
                "interaction_mode": ["PVE"],
                "gameplay_form": ["副本"],
                "rhythm_category": ["PVE"],
                "player_action": "进入伙伴副本",
                "system_feedback": "开放伙伴副本",
                "matched_gameplay_rule_ids": ["GAME-PVE-DUNGEON"],
                "matched_emotion_rule_ids": ["EMO-PLAY-001"],
                "repeat_group_key": "伙伴副本",
                "repeat_index": 1,
                "has_new_value": True,
                "creative_high_value": False,
                "emotion_score_candidate": 2,
                "output_relations": [],
                "confidence": 0.9,
                "review_status": "needs_review",
            }],
            "review_items": [],
            "blocked_items": [],
        }
        review = build_semantic_review_template(
            ai_output,
            semantic_input,
            self.taxonomy,
            self.emotion,
        )
        pending = finalize_semantic_review(
            semantic_input,
            ai_output,
            review,
            self.taxonomy,
            self.emotion,
        )
        self.assertEqual(pending["status"], "needs_review")
        self.assertEqual(pending["summary"]["pending_count"], 1)

        review["decisions"][0]["decision"] = "confirmed"
        with self.assertRaises(JourneyPackageError):
            finalize_semantic_review(
                semantic_input,
                ai_output,
                review,
                self.taxonomy,
                self.emotion,
            )
        review["reviewer"] = "tester"
        review["reviewed_at"] = "2026-07-20T12:00:00+08:00"
        confirmed = finalize_semantic_review(
            semantic_input,
            ai_output,
            review,
            self.taxonomy,
            self.emotion,
        )
        self.assertEqual(confirmed["status"], "complete")
        self.assertEqual(confirmed["summary"]["confirmed_count"], 1)
        self.assertEqual(confirmed["events"][0]["event_name"], "伙伴副本")
        self.assertEqual(confirmed["events"][0]["semantic"]["emotion_score"], 2)
        self.assertEqual(confirmed["events"][0]["semantic_review"]["reviewer"], "tester")

        review["decisions"][0]["overrides"] = {"event_name": "禁止覆盖"}
        with self.assertRaises(JourneyPackageError):
            finalize_semantic_review(
                semantic_input,
                ai_output,
                review,
                self.taxonomy,
                self.emotion,
            )

    def test_review_workspace_confirms_event_and_updates_only_game_profile(self):
        semantic_input = {
            "schema_version": "1.1",
            "task_id": "JOURNEY_SEMANTIC_V1",
            "source_fingerprint": "b" * 64,
            "session": {"session_id": "demo", "event_count": 1},
            "events": [{
                "event_id": "evt_001",
                "event_name": "伙伴副本",
                "event_type": "new_feature_unlocked",
                "time_ms": 80_000,
                "timestamp": "00:01:20.000",
                "ocr_excerpt": "伙伴副本 新功能开启",
                "evidence": {},
            }],
        }
        ai_output = {
            "schema_version": "1.0",
            "task_id": "JOURNEY_SEMANTIC_V1",
            "source_fingerprint": "b" * 64,
            "event_annotations": [{
                "event_id": "evt_001",
                "event_category": "玩法开放",
                "object_scope": ["伙伴"],
                "interaction_mode": ["PVE"],
                "gameplay_form": ["副本"],
                "rhythm_category": ["PVE"],
                "player_action": "查看伙伴副本",
                "system_feedback": "开放伙伴副本",
                "matched_gameplay_rule_ids": ["GAME-PVE-DUNGEON"],
                "matched_emotion_rule_ids": ["EMO-PLAY-001"],
                "repeat_group_key": "伙伴副本",
                "repeat_index": 1,
                "has_new_value": True,
                "creative_high_value": False,
                "emotion_score_candidate": 2,
                "output_relations": [],
                "confidence": 0.9,
                "review_status": "needs_review",
            }],
            "review_items": [],
            "blocked_items": [],
        }
        review = build_semantic_review_template(ai_output, semantic_input, self.taxonomy, self.emotion)
        review["decisions"][0]["decision"] = "confirmed"
        review["reviewer"] = "legacy-reviewer"
        review["reviewed_at"] = "2026-07-21T09:00:00+08:00"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            output_path = root / "output.json"
            review_path = root / "review.json"
            confirmed_path = root / "confirmed.json"
            profile_path = root / "profile.json"
            taxonomy_path = root / "taxonomy.json"
            emotion_path = root / "emotion.json"
            for path, payload in (
                (input_path, semantic_input),
                (output_path, ai_output),
                (review_path, review),
                (taxonomy_path, self.taxonomy),
                (emotion_path, self.emotion),
            ):
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            workspace = SemanticReviewWorkspace(
                semantic_input_path=input_path,
                ai_output_path=output_path,
                review_path=review_path,
                confirmed_output_path=confirmed_path,
                game_profile_path=profile_path,
                taxonomy_path=taxonomy_path,
                emotion_rules_path=emotion_path,
                evidence_root=None,
                game_id="qingyun",
                game_name="青云诀之伏魔",
            )
            migrated_state = workspace.state()
            self.assertEqual(migrated_state["summary"]["pending"], 1)
            self.assertEqual(migrated_state["events"][0]["decision"]["legacy_decision"], "confirmed")
            self.assertFalse(migrated_state["events"][0]["decision"]["labels_reviewed"])
            bulk_result = workspace.bulk_confirm(["evt_001"], "tester")
            self.assertEqual(bulk_result["summary"]["confirmed"], 1)
            bulk_confirmed = json.loads(confirmed_path.read_text(encoding="utf-8"))
            self.assertEqual(
                bulk_confirmed["events"][0]["semantic"]["tags"],
                ["PVE", "新副本"],
            )
            self.assertEqual(bulk_confirmed["events"][0]["semantic"]["mode_tag"], "PVE")
            self.assertEqual(bulk_confirmed["events"][0]["semantic"]["event_tag"], "新副本")
            result = workspace.save_decision({
                "event_id": "evt_001",
                "decision": "confirmed",
                "reviewer": "tester",
                "overrides": {
                    "mode_tag": "PVE",
                    "event_tag": "新副本",
                    "tags": ["PVE", "新副本"],
                },
                "review_note": "已核对",
                "save_to_game_profile": True,
                "game_term": "伙伴副本",
            })
            self.assertEqual(result["summary"]["confirmed"], 1)
            confirmed = json.loads(confirmed_path.read_text(encoding="utf-8"))
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(confirmed["status"], "complete")
            self.assertEqual(confirmed["events"][0]["semantic"]["tags"], ["PVE", "新副本"])
            self.assertEqual(profile["game_id"], "qingyun")
            self.assertEqual(profile["terms"][0]["mapping"]["gameplay_form"], ["副本"])
            self.assertEqual(profile["terms"][0]["mapping"]["tags"], ["PVE", "新副本"])

    def test_review_workspace_normalizes_legacy_tags_and_does_not_write_before_finalize(self):
        ai_output = {
            "event_annotations": [{"event_id": "evt_legacy"}],
        }
        review = {
            "decisions": [{
                "event_id": "evt_legacy",
                "decision": "confirmed",
                "overrides": {"tags": ["新功能", "养成"]},
            }],
        }
        SemanticReviewWorkspace._normalize_review(review, ai_output)
        self.assertEqual(review["decisions"][0]["overrides"]["tags"], ["新功能", "新养成系统"])

        semantic_input = {
            "source_fingerprint": "c" * 64,
            "session": {"session_id": "demo", "event_count": 1},
            "events": [{
                "event_id": "evt_legacy",
                "event_name": "仙术",
                "event_type": "new_feature_unlocked",
                "time_ms": 1_000,
                "timestamp": "00:00:01.000",
                "ocr_excerpt": "仙术 新功能开启",
                "evidence": {},
            }],
        }
        candidate = {
            "schema_version": "1.0",
            "task_id": "JOURNEY_SEMANTIC_V1",
            "source_fingerprint": "c" * 64,
            "event_annotations": [{
                "event_id": "evt_legacy",
                "event_category": "玩法开放",
                "object_scope": ["角色"],
                "interaction_mode": ["养成"],
                "gameplay_form": ["养成系统"],
                "rhythm_category": ["核心循环（爆点）"],
                "player_action": "查看仙术",
                "system_feedback": "开放仙术",
                "matched_gameplay_rule_ids": ["GAME-SYSTEM-GROWTH"],
                "matched_emotion_rule_ids": ["EMO-PLAY-003"],
                "repeat_group_key": "仙术",
                "repeat_index": 1,
                "has_new_value": True,
                "creative_high_value": False,
                "emotion_score_candidate": 1,
                "output_relations": [],
                "confidence": 0.9,
                "review_status": "needs_review",
            }],
            "review_items": [],
            "blocked_items": [],
        }
        review = build_semantic_review_template(candidate, semantic_input, self.taxonomy, self.emotion)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "input": root / "input.json",
                "candidate": root / "candidate.json",
                "review": root / "review.json",
                "confirmed": root / "confirmed.json",
                "profile": root / "profile.json",
                "taxonomy": root / "taxonomy.json",
                "emotion": root / "emotion.json",
            }
            for key, payload in (
                ("input", semantic_input),
                ("candidate", candidate),
                ("review", review),
                ("taxonomy", self.taxonomy),
                ("emotion", self.emotion),
            ):
                paths[key].write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            before = paths["review"].read_bytes()
            workspace = SemanticReviewWorkspace(
                semantic_input_path=paths["input"],
                ai_output_path=paths["candidate"],
                review_path=paths["review"],
                confirmed_output_path=paths["confirmed"],
                game_profile_path=paths["profile"],
                taxonomy_path=paths["taxonomy"],
                emotion_rules_path=paths["emotion"],
                evidence_root=None,
                game_id="demo",
                game_name="测试游戏",
            )
            with patch(
                "screen_mouse_recorder.journey_analysis.review_workspace.finalize_semantic_review",
                side_effect=JourneyPackageError("模拟终结失败"),
            ):
                with self.assertRaises(JourneyPackageError):
                    workspace.save_decision({
                        "event_id": "evt_legacy",
                        "decision": "confirmed",
                        "reviewer": "tester",
                        "overrides": {
                            "mode_tag": "系统",
                            "event_tag": "新养成系统",
                            "tags": ["系统", "新养成系统"],
                        },
                    })
            self.assertEqual(paths["review"].read_bytes(), before)
            self.assertFalse(paths["confirmed"].exists())


if __name__ == "__main__":
    unittest.main()
