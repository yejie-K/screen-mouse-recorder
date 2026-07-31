from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.manual_frame_review import (  # noqa: E402
    ManualFrameReviewError,
    ManualFrameReviewWorkspace,
)


def candidate(**updates):
    value = {
        "id": "manual_evt_001",
        "title": "仙术功能开启",
        "eventKind": "new_feature",
        "status": "needs_review",
        "timeMs": 1234,
        "timecode": "00:00:01.234",
        "source": "manual_frame",
        "confidence": 1,
        "ocrText": "尚未执行 OCR",
        "evidenceFile": "click_keyframes_001.png · tile_001",
        "eventId": "evt_001",
        "note": "人工选帧",
        "contactSheet": "click_keyframes_001.png",
        "contactSheetTileId": "tile_22",
    }
    value.update(updates)
    return value


class ManualFrameReviewWorkspaceTests(unittest.TestCase):
    def workspace(self, root: Path, *, linked: bool = False) -> ManualFrameReviewWorkspace:
        runtime = root / "runtime"
        runtime.mkdir()
        payload = {
            "projectName": "测试Session",
            "sessionId": "session_001",
            "videoUrl": "/runtime/recording.mp4",
            "contactSheets": [],
            "candidates": [],
        }
        if linked:
            payload.update(sourceIndex="keyframes_index.json", videoFile="recording.mp4")
            (runtime / "keyframes_index.json").write_text("{}", encoding="utf-8")
        (runtime / "review_session.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        (runtime / "recording.mp4").write_bytes(b"video")
        return ManualFrameReviewWorkspace(runtime_dir=runtime, state_path=root / "manual_frame_review.json")

    def test_saves_and_reloads_manual_candidates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self.workspace(root)
            self.assertEqual(workspace.state()["manualCandidates"], [])
            result = workspace.save({"sessionId": "session_001", "candidates": [candidate()]})
            self.assertEqual(result["candidate_count"], 1)
            state = workspace.state()
            self.assertEqual(state["manualCandidates"][0]["title"], "仙术功能开启")
            saved = json.loads((root / "manual_frame_review.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], "1.0")
            self.assertEqual(saved["session_id"], "session_001")
            selected = json.loads((root / "selected_ocr_tiles.json").read_text(encoding="utf-8"))
            self.assertEqual(selected["selections"][0]["tile_index"], 22)
            self.assertEqual(selected["selections"][0]["event_name"], "仙术功能开启")
            self.assertNotIn("source_index", selected)
            self.assertFalse(result["selected_ocr_ready"])
            self.assertTrue(result["selected_ocr_blockers"])

    def test_linked_runtime_writes_real_relative_ocr_sources(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self.workspace(root, linked=True)
            result = workspace.save({"sessionId": "session_001", "candidates": [candidate()]})
            selected = json.loads((root / "selected_ocr_tiles.json").read_text(encoding="utf-8"))
            self.assertEqual(selected["source_index"], "runtime/keyframes_index.json")
            self.assertEqual(selected["source_video"], "runtime/recording.mp4")
            self.assertTrue(result["selected_ocr_ready"])

    def test_empty_selection_removes_stale_ocr_adapter(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self.workspace(root)
            workspace.save({"sessionId": "session_001", "candidates": [candidate()]})
            selected = root / "selected_ocr_tiles.json"
            self.assertTrue(selected.is_file())
            result = workspace.save({"sessionId": "session_001", "candidates": []})
            self.assertFalse(selected.exists())
            self.assertEqual(result["selected_ocr_count"], 0)
            self.assertEqual(result["selected_ocr_file"], "")

    def test_rejects_non_manual_or_wrong_session_candidates(self):
        with TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            with self.assertRaises(ManualFrameReviewError):
                workspace.save({"sessionId": "other", "candidates": []})
            with self.assertRaises(ManualFrameReviewError):
                workspace.save({"sessionId": "session_001", "candidates": [candidate(source="ai")]})

    def test_runtime_file_stays_inside_runtime_directory(self):
        with TemporaryDirectory() as directory:
            workspace = self.workspace(Path(directory))
            self.assertEqual(workspace.runtime_file("recording.mp4").name, "recording.mp4")
            with self.assertRaises(ManualFrameReviewError):
                workspace.runtime_file("../manual_frame_review.json")


if __name__ == "__main__":
    unittest.main()
