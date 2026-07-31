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
    MetricReviewWorkspace,
    build_metric_review_template,
    finalize_metric_review,
)
from screen_mouse_recorder.journey_analysis.package import JourneyPackageError  # noqa: E402


class MetricReviewTests(unittest.TestCase):
    def _candidates(self) -> dict:
        def metric(observation_id: str, key: str, value, time_ms: int) -> dict:
            return {
                "observation_id": observation_id,
                "session_id": "session_demo",
                "time_ms": time_ms,
                "timestamp": f"00:00:{time_ms // 1000:02d}.000",
                "source": "automatic",
                "evidence": {"source_image": "frame.png", "frame_index": time_ms // 1000},
                "metric_key": key,
                "raw_text": str(value or "未识别"),
                "ocr_text": str(value or "未识别"),
                "confidence": 0.96 if value is not None else 0.5,
                "parsed_value": value,
                "parsed_fields": {},
                "unit": "",
                "region_id": f"roi_{key}",
                "review": {"status": "pending", "reviewer": "", "reviewed_at": "", "note": ""},
            }

        return {
            "schema_version": "2.0",
            "task_id": "JOURNEY_METRIC_OBSERVATIONS_V2",
            "source_fingerprint": "fingerprint-demo",
            "status": "needs_review",
            "scan_scope": "all_extracted_frames",
            "session": {"session_id": "session_demo"},
            "summary": {"observation_count": 2, "pending": 2, "confirmed": 0, "excluded": 0},
            "metrics": [
                metric("metric_power_001", "combat_power", 110_400, 1000),
                metric("metric_level_002", "level_rebirth", None, 2000),
            ],
            "compatibility": {},
        }

    def test_template_and_finalizer_keep_candidates_pending_until_human_decision(self):
        candidates = self._candidates()
        review = build_metric_review_template(candidates)
        result = finalize_metric_review(candidates, review)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["summary"]["pending"], 2)
        self.assertEqual(result["metrics"][0]["review"]["status"], "pending")
        self.assertEqual(
            result["compatibility"]["pending_observation_ids"],
            ["metric_power_001", "metric_level_002"],
        )

    def test_workspace_writes_separate_review_and_confirmed_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidates_path = root / "metric_observations_v2.json"
            review_path = root / "journey_metric_review.json"
            confirmed_path = root / "confirmed_metric_observations_v2.json"
            evidence_root = root / "evidence"
            evidence_root.mkdir()
            Image.new("RGB", (80, 60), "white").save(evidence_root / "frame.png")
            original = self._candidates()
            candidates_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            original_bytes = candidates_path.read_bytes()

            workspace = MetricReviewWorkspace(
                candidates_path=candidates_path,
                review_path=review_path,
                confirmed_output_path=confirmed_path,
                evidence_root=evidence_root,
            )
            self.assertTrue(review_path.is_file())
            self.assertTrue(confirmed_path.is_file())
            self.assertEqual(workspace.state()["summary"]["pending"], 2)
            self.assertGreaterEqual(workspace.state()["summary"]["flagged"], 1)
            self.assertEqual(workspace.evidence_for("metric_power_001"), evidence_root / "frame.png")
            with self.assertRaises(JourneyPackageError):
                workspace.bulk_confirm(["metric_power_001"], "tester")

            state = workspace.save_decision({
                "observation_id": "metric_power_001",
                "decision": "confirmed",
                "reviewer": "tester",
                "overrides": {
                    "metric_key": "combat_power",
                    "parsed_value": 110_400,
                    "parsed_fields": {},
                    "unit": "",
                },
                "review_note": "已核对画面",
            })
            self.assertEqual(state["summary"]["confirmed"], 1)
            state = workspace.save_decision({
                "observation_id": "metric_level_002",
                "decision": "excluded",
                "reviewer": "tester",
                "overrides": {
                    "metric_key": "level_rebirth",
                    "parsed_value": None,
                    "parsed_fields": {},
                    "unit": "",
                },
                "review_note": "画面遮挡",
            })
            self.assertEqual(state["summary"]["pending"], 0)
            final = json.loads(confirmed_path.read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "complete")
            self.assertEqual(final["summary"]["confirmed"], 1)
            self.assertEqual(final["summary"]["excluded"], 1)
            self.assertEqual(final["metrics"][0]["parsed_value"], 110_400)
            self.assertEqual(candidates_path.read_bytes(), original_bytes)

    def test_confirm_requires_reviewer_and_effective_value(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidates_path = root / "candidates.json"
            candidates_path.write_text(json.dumps(self._candidates(), ensure_ascii=False), encoding="utf-8")
            workspace = MetricReviewWorkspace(
                candidates_path=candidates_path,
                review_path=root / "review.json",
                confirmed_output_path=root / "confirmed.json",
            )
            with self.assertRaises(JourneyPackageError):
                workspace.save_decision({
                    "observation_id": "metric_level_002",
                    "decision": "confirmed",
                    "reviewer": "",
                    "overrides": {},
                })
            with self.assertRaises(JourneyPackageError):
                workspace.save_decision({
                    "observation_id": "metric_level_002",
                    "decision": "confirmed",
                    "reviewer": "tester",
                    "overrides": {},
                })


if __name__ == "__main__":
    unittest.main()
