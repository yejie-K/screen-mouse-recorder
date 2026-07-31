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
from screen_mouse_recorder.journey_analysis.metric_review import MetricReviewWorkspace
from screen_mouse_recorder.journey_analysis.package import JourneyPackageError


STATIC_ROOT = ROOT / "tools" / "metric_review_web"


class MetricReviewHandler(BaseHTTPRequestHandler):
    workspace: MetricReviewWorkspace

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

    def _send_file(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            request_path = strip_route_prefix(self.path, "/metrics")
            if request_path == "/workspace-shell.css":
                self._send_file(ROOT / "tools" / "workspace_shell.css")
                return
            if request_path == "/workspace-shell.js":
                self._send_file(ROOT / "tools" / "workspace_shell.js")
                return
            if request_path == "/api/state":
                self._json(self.workspace.state())
                return
            if request_path.startswith("/api/evidence/"):
                observation_id = request_path.removeprefix("/api/evidence/").split("?", 1)[0]
                path = self.workspace.evidence_for(observation_id)
                if path is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_file(path)
                return
            static_name = "index.html" if request_path in {"/", "/index.html"} else request_path.removeprefix("/")
            if static_name not in {"index.html", "styles.css", "app.js"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_file(STATIC_ROOT / static_name)
        except (JourneyPackageError, OSError, json.JSONDecodeError) as exc:
            self._error(exc, 500)

    def do_POST(self) -> None:
        try:
            payload = self._body()
            request_path = strip_route_prefix(self.path, "/metrics")
            if request_path == "/api/decision":
                self._json(self.workspace.save_decision(payload))
                return
            if request_path == "/api/bulk-confirm":
                observation_ids = payload.get("observation_ids")
                if not isinstance(observation_ids, list):
                    raise JourneyPackageError("observation_ids必须是数组")
                self._json(self.workspace.bulk_confirm(
                    list(map(str, observation_ids)),
                    str(payload.get("reviewer") or ""),
                ))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (JourneyPackageError, ValueError, OSError, json.JSONDecodeError) as exc:
            self._error(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="启动指标结果人工复核工作台")
    parser.add_argument("candidates", type=Path, help="metric_observations_v2.json")
    parser.add_argument("--review", type=Path, help="人工复核决定文件")
    parser.add_argument("--confirmed-output", type=Path, help="复核后的指标结果")
    parser.add_argument("--evidence-root", type=Path, help="来源帧或裁剪图根目录")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    candidates = args.candidates.resolve()
    review = (args.review or candidates.with_name("journey_metric_review.json")).resolve()
    confirmed = (
        args.confirmed_output
        or candidates.with_name("confirmed_metric_observations_v2.json")
    ).resolve()
    MetricReviewHandler.workspace = MetricReviewWorkspace(
        candidates_path=candidates,
        review_path=review,
        confirmed_output_path=confirmed,
        evidence_root=args.evidence_root,
    )
    server = ThreadingHTTPServer((args.host, args.port), MetricReviewHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"指标复核工作台: {url}")
    print(f"复核文件: {review}")
    print(f"确认输出: {confirmed}")
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
