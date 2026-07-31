from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.manual_frame_review import ManualFrameReviewWorkspace
from screen_mouse_recorder.analysis_handoff import write_analysis_handoff
from tools.serve_journey_workspace import (
    JourneyWorkspaceHandler,
    RouteApplication,
    WorkspaceApplications,
    WorkspaceDirectoryRegistry,
    _discover_session_entries,
    _resolve_startup_workspace,
)
from tools.serve_manual_frame_review import ManualFrameReviewHandler
from tools.prepare_journey_run import prepare_journey_run
from tools.workspace_http import strip_route_prefix


class _Applications:
    def __init__(self, workspace: ManualFrameReviewWorkspace) -> None:
        self.application = RouteApplication(ManualFrameReviewHandler, workspace)
        self.selected_id = "workspace-current"

    def get(self, section: str):
        return self.application if section == "manual" else None

    def state(self) -> dict:
        return {
            "status": "ready",
            "routes": {"manual": "/manual/"},
            "available": ["manual"],
            "stages": {
                "region_scan": {"status": "stale", "reason": "scan fingerprint changed"},
                "event_review": {"status": "stale"},
                "metric_review": {"status": "stale"},
            },
        }

    def list_workspaces(self) -> dict:
        return {
            "status": "ready",
            "current_id": self.selected_id,
            "sessions": [{
                "id": self.selected_id,
                "session_id": "session_001",
                "game_name": "demo",
                "label": "demo · session_001",
                "prepared": True,
                "current": True,
                "reason": "",
            }],
        }

    def preparation_state(self) -> dict:
        return {"status": "idle"}

    def select_workspace(self, workspace_id: str) -> dict:
        if workspace_id != self.selected_id:
            raise ValueError("Session不存在")
        return {**self.list_workspaces(), "selected": workspace_id, "changed": False}


class WorkspaceServerTests(unittest.TestCase):
    def test_first_downstream_open_syncs_with_required_rule_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = WorkspaceApplications.__new__(WorkspaceApplications)
            app.root = root
            app._lock = threading.RLock()
            app._applications = {}
            app._downstream_error = ""
            app.manifest = {
                "stages": {
                    "region_scan": {"status": "complete"},
                    "event_review": {"status": "blocked"},
                    "metric_review": {"status": "blocked"},
                },
                "artifacts": {
                    "event_review_manifest": "event_review/manifest.json",
                    "metric_observations": "scan/metrics.json",
                    "metric_review": "metric_review/review.json",
                },
            }

            def assert_rules(workspace, *, taxonomy_path, emotion_rules_path):
                self.assertEqual(workspace, root)
                self.assertEqual(taxonomy_path, ROOT / "rules" / "gameplay_taxonomy_v0.1.json")
                self.assertEqual(emotion_rules_path, ROOT / "rules" / "emotion_rules_v0.1.json")
                raise ValueError("stop after argument verification")

            with (
                patch("tools.serve_journey_workspace.refresh_journey_workspace", return_value=app.manifest),
                patch("tools.serve_journey_workspace.sync_journey_workspace", side_effect=assert_rules),
            ):
                self.assertIsNone(app.get("events"))
            self.assertEqual(app._downstream_error, "stop after argument verification")

    def test_route_prefix_preserves_query(self):
        self.assertEqual(strip_route_prefix("/manual/api/state?x=1", "/manual"), "/api/state?x=1")
        self.assertEqual(strip_route_prefix("/regions", "regions"), "/")
        self.assertEqual(strip_route_prefix("/api/state", "/manual"), "/api/state")

    def test_single_server_dispatches_manual_api_and_runtime(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "review_session.json").write_text(json.dumps({
                "sessionId": "session_001",
                "projectName": "demo",
                "durationMs": 1000,
                "videoFile": "recording.mp4",
                "videoUrl": "/runtime/recording.mp4",
                "sourceIndex": "index.json",
                "contactSheets": [],
                "candidates": [],
            }), encoding="utf-8")
            (runtime / "recording.mp4").write_bytes(b"0123456789")
            (runtime / "index.json").write_text("{}", encoding="utf-8")
            workspace = ManualFrameReviewWorkspace(
                runtime_dir=runtime,
                state_path=root / "manual_frame_review.json",
            )
            JourneyWorkspaceHandler.applications = _Applications(workspace)
            from http.server import ThreadingHTTPServer

            server = ThreadingHTTPServer(("127.0.0.1", 0), JourneyWorkspaceHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", "/manual/api/state")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["sessionId"], "session_001")

                connection.request("GET", "/manual/runtime/recording.mp4", headers={"Range": "bytes=2-5"})
                response = connection.getresponse()
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), b"2345")

                connection.request("GET", "/workspace-shell.css")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                stylesheet = response.read().decode("utf-8")
                self.assertIn("--workspace-shell-min-width: 1100px", stylesheet)
                self.assertIn(".workspace-shell-main", stylesheet)

                connection.request("GET", "/workspace-shell.js")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                shell_script = response.read().decode("utf-8")
                self.assertIn('/api/workspace/select', shell_script)
                self.assertIn('/api/workspace/browse', shell_script)
                self.assertIn('/api/workspace/prepare', shell_script)
                self.assertIn('/api/shutdown', shell_script)
                self.assertIn('退出分析', shell_script)
                self.assertIn('Session准备中', shell_script)
                self.assertIn('workspace-shell-preparation__track', shell_script)

                connection.request("GET", "/api/workspace/prepare")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["status"], "idle")

                connection.request("GET", "/api/workspaces")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                sessions = json.loads(response.read())
                self.assertEqual(sessions["current_id"], "workspace-current")
                self.assertNotIn("path", sessions["sessions"][0])

                payload = json.dumps({"workspace_id": "workspace-current"}).encode("utf-8")
                connection.request(
                    "POST",
                    "/api/workspace/select",
                    body=payload,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertFalse(json.loads(response.read())["changed"])

                connection.request("GET", "/events/")
                response = connection.getresponse()
                self.assertEqual(response.status, 503)
                unavailable = response.read().decode("utf-8")
                self.assertIn("scan fingerprint changed", unavailable)
                self.assertIn("workspace-shell-header", unavailable)
                connection.request("POST", "/api/shutdown", body=b"{}", headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 202)
                self.assertEqual(json.loads(response.read())["status"], "stopping")
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_startup_workspace_uses_explicit_path_or_latest_discovered_manifest(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = root / "explicit"
            older = root / "outputs" / "older"
            newer = root / "outputs" / "newer"
            for workspace in (explicit, older, newer):
                workspace.mkdir(parents=True)
                (workspace / "journey_workspace.json").write_text("{}", encoding="utf-8")
            old_time = time.time() - 10
            os.utime(older / "journey_workspace.json", (old_time, old_time))

            self.assertEqual(_resolve_startup_workspace(explicit), explicit.resolve())
            with (
                patch("tools.serve_journey_workspace.ROOT", root),
                patch.object(WorkspaceDirectoryRegistry, "paths", return_value=()),
            ):
                self.assertEqual(_resolve_startup_workspace(None), newer.resolve())

    def test_browse_starts_from_sc_recording_library(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            recordings = root / "sessions" / "recordings"
            recordings.mkdir(parents=True)
            application = WorkspaceApplications.__new__(WorkspaceApplications)
            application.root = root / "outputs" / "workspace"
            application.registry = WorkspaceDirectoryRegistry(root / "registry.json")
            with patch("tools.serve_journey_workspace.ROOT", root):
                self.assertEqual(application.browse_initial_directory(), recordings.resolve())

    def test_all_review_pages_use_the_shared_shell(self):
        pages = (
            ROOT / "tools" / "region_profile_review_web" / "index.html",
            ROOT / "tools" / "journey_review_web" / "index.html",
            ROOT / "tools" / "metric_review_web" / "index.html",
        )
        for page in pages:
            content = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                self.assertIn('/workspace-shell.css', content)
                self.assertIn('workspace-shell-header', content)
                self.assertIn('workspace-shell-toolbar', content)
                self.assertIn('workspace-shell-main', content)
                self.assertIn('workspace-shell-session', content)
                self.assertIn('/workspace-shell.js', content)

        manual_index = (ROOT / "tools" / "manual_frame_review_web" / "index.html").read_text(encoding="utf-8")
        manual_component = (ROOT / "tools" / "manual_frame_review_web" / "src" / "components" / "ReviewWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn('/workspace-shell.css', manual_index)
        self.assertIn('workspace-shell-header', manual_component)
        self.assertIn('workspace-shell-toolbar', manual_component)
        self.assertIn('workspace-shell-main', manual_component)
        self.assertIn('workspace-shell-session', manual_component)
        self.assertIn('/workspace-shell.js', manual_index)

    def test_workspace_discovery_uses_opaque_ids_and_marks_current(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "workspace_a"
            other = root / "nested" / "workspace_b"
            current.mkdir(parents=True)
            other.mkdir(parents=True)
            for target, session_id in ((current, "session_a"), (other, "session_b")):
                (target / "journey_workspace.json").write_text(json.dumps({
                    "session": {
                        "session_id": session_id,
                        "game_name": "测试游戏",
                        "duration_ms": 1000,
                    },
                }), encoding="utf-8")
            nested_runtime = other / "runtime"
            nested_runtime.mkdir()
            (nested_runtime / "recording.mp4").write_bytes(b"workspace video")

            entries = _discover_session_entries((root,), current)
            prepared = [item for item in entries if item["prepared"]]
            raw = [item for item in entries if not item["prepared"]]
            self.assertEqual(len(prepared), 2)
            self.assertEqual(raw, [])
            self.assertEqual(sum(bool(item["current"]) for item in prepared), 1)
            self.assertTrue(all("path" not in item for item in prepared))
            self.assertTrue(all(len(str(item["id"])) == 16 for item in prepared))

    def test_external_raw_session_is_discovered_from_selected_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current"
            external = root / "external_library" / "session_external"
            current.mkdir()
            external.mkdir(parents=True)
            (current / "journey_workspace.json").write_text(json.dumps({
                "session": {"session_id": "current", "game_name": "demo"},
            }), encoding="utf-8")
            (external / "recording.mp4").write_bytes(b"video")

            entries = _discover_session_entries((root / "external_library",), current)
            raw = [item for item in entries if not item["prepared"]]
            self.assertEqual(len(raw), 1)
            self.assertEqual(raw[0]["session_id"], "session_external")
            self.assertTrue(raw[0]["preparable"])
            self.assertEqual(raw[0]["source_mode"], "plain_video")
            self.assertIn("10秒", raw[0]["reason"])
            self.assertNotIn("path", raw[0])

    def test_background_preparation_writes_workspace_under_session_analysis_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current"
            session = root / "portable_session"
            current.mkdir()
            session.mkdir()
            (current / "journey_workspace.json").write_text(json.dumps({
                "session": {"session_id": "current", "game_name": "demo"},
            }), encoding="utf-8")
            (session / "recording.mp4").write_bytes(b"video")
            (session / "mouse_events.jsonl").write_text("{}\n", encoding="utf-8")
            (session / "session_meta.json").write_text(json.dumps({
                "session_id": "portable_session",
                "video": {"file": "recording.mp4"},
            }), encoding="utf-8")

            app = WorkspaceApplications.__new__(WorkspaceApplications)
            app.root = current.resolve()
            app.registry = WorkspaceDirectoryRegistry(root / "local" / "journey_sessions.json")
            app.discovery_roots = (current.resolve(), session.resolve())
            app._lock = threading.RLock()
            app._session_entries_cache = []
            app._session_entries_cached_at = 0.0
            app._prepare_thread = None
            app._prepare_state = {"status": "idle"}
            raw = next(item for item in app._session_entries() if not item["prepared"])
            captured: dict = {}

            def fake_prepare(session_dir, run_dir, **kwargs):
                captured.update({"session_dir": session_dir, "run_dir": run_dir, **kwargs})
                kwargs["progress"](2, 4, "正在抽帧")
                workspace = kwargs["workspace_dir"]
                workspace.mkdir(parents=True)
                (workspace / "journey_workspace.json").write_text(json.dumps({
                    "session": {"session_id": "portable_session", "game_name": kwargs["game_name"]},
                }), encoding="utf-8")
                return {"status": "ready"}

            with patch("tools.serve_journey_workspace.prepare_journey_run", side_effect=fake_prepare):
                started = app.start_preparation(raw["id"], "测试游戏")
                self.assertIn(started["status"], {"starting", "running", "complete"})
                deadline = time.monotonic() + 3
                while app.preparation_state()["status"] in {"starting", "running"} and time.monotonic() < deadline:
                    time.sleep(0.01)

            state = app.preparation_state()
            self.assertEqual(state["status"], "complete")
            self.assertEqual(state["percent"], 100)
            self.assertEqual(captured["session_dir"], session.resolve())
            self.assertEqual(captured["workspace_dir"].parent, captured["run_dir"])
            self.assertTrue((session / "analysis_output" / "journey_workspace" / "journey_workspace.json").is_file())
            self.assertFalse(captured["run_dir"].exists())
            self.assertNotIn(str(session), json.dumps(state, ensure_ascii=False))

    def test_prepare_run_keeps_published_report_paths_relative(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            staging = session / "analysis_output" / ".journey_prepare_test"
            workspace = session / "analysis_output" / "journey_workspace"
            session.mkdir()
            (session / "recording.mp4").write_bytes(b"video")
            (session / "mouse_events.jsonl").write_text("{}\n", encoding="utf-8")
            (session / "session_meta.json").write_text(json.dumps({
                "session_id": "session",
                "video": {"file": "recording.mp4"},
            }), encoding="utf-8")

            def fake_generate(config, progress):
                config.output_dir.mkdir(parents=True)
                sheet = config.output_dir / "keyframes_click_sheet_001.png"
                sheet.write_bytes(b"png")
                index = config.output_dir / "keyframes_click_sheet_index.json"
                index.write_text(json.dumps({
                    "frames": [{
                        "index": 1,
                        "seconds": 0.0,
                        "sheet": sheet.name,
                        "sheet_row": 1,
                        "sheet_col": 1,
                    }],
                    "selection": {},
                }), encoding="utf-8")
                progress(1, 1, "完成")
                return SimpleNamespace(
                    index_json=index,
                    sheet_paths=[sheet],
                    events_total=1,
                    events_kept=1,
                    events_skipped=0,
                )

            def fake_initialize(_session, _index, output, **_kwargs):
                output.mkdir(parents=True)
                (output / "journey_workspace.json").write_text("{}", encoding="utf-8")
                return {"stages": {"manual_review": {"status": "ready"}}}

            with (
                patch("tools.prepare_journey_run._preflight", return_value={
                    "schema_version": "1.0",
                    "source": {},
                }),
                patch("tools.prepare_journey_run.generate_click_keyframe_sheets", side_effect=fake_generate),
                patch("tools.prepare_journey_run.initialize_journey_workspace", side_effect=fake_initialize),
            ):
                report = prepare_journey_run(
                    session,
                    staging,
                    game_id="demo",
                    game_name="测试游戏",
                    workspace_dir=workspace,
                )

            published = json.loads((workspace / "prepare_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["workspace"], "../journey_workspace")
            self.assertEqual(published["workspace"], "journey_workspace.json")
            self.assertEqual(published["preflight"], "preflight.json")
            self.assertNotIn(str(root), json.dumps(published, ensure_ascii=False))

    def test_prepare_run_reuses_valid_recorder_handoff_without_extracting_again(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            report_dir = session / "auto_report"
            report_dir.mkdir(parents=True)
            (session / "recording.mp4").write_bytes(b"video")
            (session / "mouse_events.jsonl").write_text("{}\n", encoding="utf-8")
            (session / "session_meta.json").write_text(json.dumps({
                "session_id": "session_handoff",
                "video": {"file": "recording.mp4"},
            }), encoding="utf-8")
            sheet = report_dir / "keyframes_click_sheet_001.png"
            sheet.write_bytes(b"png")
            index = report_dir / "keyframes_click_sheet_index.json"
            index.write_text(json.dumps({
                "events_total": 2,
                "frames": [{
                    "index": 1,
                    "seconds": 1.0,
                    "sheet": sheet.name,
                    "sheet_row": 1,
                    "sheet_col": 1,
                }],
                "selection": {},
            }), encoding="utf-8")
            write_analysis_handoff(
                session,
                frame_index_path=index,
                contact_sheet_paths=[sheet],
            )

            def fake_initialize(source_session, source_index, output, **_kwargs):
                self.assertEqual(source_session, session.resolve())
                self.assertEqual(source_index, index.resolve())
                output.mkdir(parents=True)
                (output / "journey_workspace.json").write_text("{}", encoding="utf-8")
                return {"stages": {}}

            with (
                patch("tools.prepare_journey_run.generate_click_keyframe_sheets") as generate,
                patch("tools.prepare_journey_run.initialize_journey_workspace", side_effect=fake_initialize),
            ):
                result = prepare_journey_run(
                    session,
                    root / "run",
                    game_id="demo",
                    game_name="测试游戏",
                )

            generate.assert_not_called()
            self.assertEqual(result["contact_sheets"]["source_mode"], "recorder_handoff")
            self.assertEqual(result["contact_sheets"]["frame_policy"], "CLICK_SUMMARY_V1")

    def test_prepare_run_supports_plain_video_with_interval_events(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "plain_video"
            session.mkdir()
            (session / "recording.mp4").write_bytes(b"video")
            captured: dict = {}

            def fake_generate(config, progress):
                captured["config"] = config
                captured["events"] = [
                    json.loads(line)
                    for line in config.events_path.read_text(encoding="utf-8").splitlines()
                ]
                config.output_dir.mkdir(parents=True)
                sheet = config.output_dir / "keyframes_click_sheet_001.png"
                sheet.write_bytes(b"png")
                index = config.output_dir / "keyframes_click_sheet_index.json"
                index.write_text(json.dumps({
                    "frames": [{
                        "index": 1,
                        "seconds": 0.0,
                        "sheet": sheet.name,
                        "sheet_row": 1,
                        "sheet_col": 1,
                    }],
                    "selection": {},
                }), encoding="utf-8")
                progress(1, 1, "完成")
                return SimpleNamespace(index_json=index, sheet_paths=[sheet])

            def fake_initialize(source_session, _source_index, output, **_kwargs):
                captured["derived_session"] = source_session
                output.mkdir(parents=True)
                (output / "journey_workspace.json").write_text("{}", encoding="utf-8")
                return {"stages": {}}

            video_info = SimpleNamespace(duration_seconds=25.0, fps=30.0, width=1080, height=1920)
            with (
                patch("tools.prepare_journey_run.probe_video", return_value=video_info),
                patch("tools.prepare_journey_run.generate_click_keyframe_sheets", side_effect=fake_generate),
                patch("tools.prepare_journey_run.initialize_journey_workspace", side_effect=fake_initialize),
            ):
                result = prepare_journey_run(
                    session,
                    root / "run",
                    game_id="demo",
                    game_name="测试游戏",
                )

            self.assertEqual(result["contact_sheets"]["source_mode"], "plain_video_interval")
            self.assertEqual([item["t_video_ms"] for item in captured["events"]], [0, 10_000, 20_000])
            derived = captured["derived_session"]
            meta = json.loads((derived / "session_meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["derived_from_plain_video"])
            self.assertTrue((derived / "recording.mp4").is_file())

    def test_recent_workspace_registry_is_machine_local_and_tolerates_stale_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "local_app_data" / "journey_sessions.json"
            first = root / "external_a"
            second = root / "external_b"
            first.mkdir()
            second.mkdir()
            registry = WorkspaceDirectoryRegistry(registry_path)

            registry.add(first)
            registry.add(second)
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(registry.paths(), (second.resolve(), first.resolve()))

            first.rmdir()
            self.assertEqual(registry.paths(), (second.resolve(),))

    def test_register_external_directory_suggests_single_prepared_workspace_without_exposing_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current"
            external = root / "portable_data" / "run_001" / "workspace"
            current.mkdir()
            external.mkdir(parents=True)
            for target, session_id in ((current, "current"), (external, "external")):
                (target / "journey_workspace.json").write_text(json.dumps({
                    "session": {"session_id": session_id, "game_name": "测试游戏"},
                }), encoding="utf-8")

            app = WorkspaceApplications.__new__(WorkspaceApplications)
            app.root = current.resolve()
            app.registry = WorkspaceDirectoryRegistry(root / "local" / "journey_sessions.json")
            app.discovery_roots = (current.resolve(),)
            app._lock = threading.RLock()
            app._session_entries_cache = []
            app._session_entries_cached_at = 0.0
            app._prepare_thread = None
            app._prepare_state = {"status": "idle"}

            payload = app.register_workspace_directory(root / "portable_data")
            self.assertTrue(payload["suggested_id"])
            self.assertEqual(len([item for item in payload["sessions"] if item["prepared"]]), 2)
            self.assertTrue(all("path" not in item for item in payload["sessions"]))
            self.assertEqual(app.registry.paths(), ((root / "portable_data").resolve(),))


if __name__ == "__main__":
    unittest.main()
