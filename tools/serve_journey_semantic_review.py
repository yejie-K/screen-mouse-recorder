#!/usr/bin/env python3
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sys
import threading
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.workspace_http import strip_route_prefix  # noqa: E402
from screen_mouse_recorder.journey_analysis.package import JourneyPackageError
from screen_mouse_recorder.journey_analysis.review_workspace import SemanticReviewWorkspace


STATIC_ROOT = ROOT / "tools" / "journey_review_web"


class ReviewHandler(BaseHTTPRequestHandler):
    workspace: SemanticReviewWorkspace

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc: Exception, status: int = 400) -> None:
        self._json({"status": "error", "message": str(exc)}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            raise JourneyPackageError("请求体为空或过大")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise JourneyPackageError("请求体必须是JSON对象")
        return payload

    def do_GET(self) -> None:
        try:
            request_path = strip_route_prefix(self.path, "/events")
            if request_path == "/workspace-shell.css":
                body = (ROOT / "tools" / "workspace_shell.css").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if request_path == "/workspace-shell.js":
                body = (ROOT / "tools" / "workspace_shell.js").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if request_path == "/api/state":
                self._json(self.workspace.state())
                return
            if request_path.startswith("/api/evidence/"):
                event_id = request_path.removeprefix("/api/evidence/").split("?", 1)[0]
                path = self.workspace.evidence_for(event_id)
                if path is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                body = path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            static_name = "index.html" if request_path in {"/", "/index.html"} else request_path.removeprefix("/")
            if static_name not in {"index.html", "styles.css", "app.js"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            path = STATIC_ROOT / static_name
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (JourneyPackageError, OSError, json.JSONDecodeError) as exc:
            self._error(exc, 500)

    def do_POST(self) -> None:
        try:
            payload = self._body()
            request_path = strip_route_prefix(self.path, "/events")
            if request_path == "/api/decision":
                self._json(self.workspace.save_decision(payload))
                return
            if request_path == "/api/bulk-confirm":
                event_ids = payload.get("event_ids")
                if not isinstance(event_ids, list):
                    raise JourneyPackageError("event_ids必须是数组")
                self._json(self.workspace.bulk_confirm(list(map(str, event_ids)), str(payload.get("reviewer") or "")))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (JourneyPackageError, ValueError, OSError, json.JSONDecodeError) as exc:
            self._error(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="启动游戏历程语义人工复核工作台")
    parser.add_argument("semantic_input", type=Path)
    parser.add_argument("ai_output", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--confirmed-output", type=Path, required=True)
    parser.add_argument("--game-profile", type=Path, required=True)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--game-name", required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    workspace = SemanticReviewWorkspace(
        semantic_input_path=args.semantic_input,
        ai_output_path=args.ai_output,
        review_path=args.review,
        confirmed_output_path=args.confirmed_output,
        game_profile_path=args.game_profile,
        taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
        emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
        evidence_root=args.evidence_root,
        game_id=args.game_id,
        game_name=args.game_name,
    )
    ReviewHandler.workspace = workspace
    server = ThreadingHTTPServer((args.host, args.port), ReviewHandler)
    url = f"http://{args.host}:{server.server_port}"
    print(json.dumps({"status": "ready", "url": url}, ensure_ascii=False), flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
