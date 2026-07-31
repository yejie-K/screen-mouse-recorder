#!/usr/bin/env python3
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sys
import threading
from urllib.parse import unquote, urlsplit
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.workspace_http import strip_route_prefix  # noqa: E402
from screen_mouse_recorder.journey_analysis.manual_frame_review import (  # noqa: E402
    ManualFrameReviewError,
    ManualFrameReviewWorkspace,
)


STATIC_ROOT = ROOT / "tools" / "manual_frame_review_web" / "dist"
RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)$")


class ManualFrameReviewHandler(BaseHTTPRequestHandler):
    workspace: ManualFrameReviewWorkspace

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

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 10_000_000:
            raise ManualFrameReviewError("请求体为空或过大")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ManualFrameReviewError("请求体必须是对象")
        return payload

    def _send_file(self, path: Path) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            match = RANGE_PATTERN.fullmatch(range_header.strip())
            if not match:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            first, last = match.groups()
            if not first:
                suffix = int(last or 0)
                start = max(0, size - suffix)
            else:
                start = int(first)
                end = min(size - 1, int(last)) if last else size - 1
            if start >= size or start > end:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining > 0:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self) -> None:
        try:
            path = unquote(urlsplit(strip_route_prefix(self.path, "/manual")).path)
            if path == "/workspace-shell.css":
                self._send_file(ROOT / "tools" / "workspace_shell.css")
                return
            if path == "/workspace-shell.js":
                self._send_file(ROOT / "tools" / "workspace_shell.js")
                return
            if path == "/api/state":
                self._json(self.workspace.state())
                return
            if path.startswith("/runtime/"):
                self._send_file(self.workspace.runtime_file(path.removeprefix("/runtime/")))
                return
            static_name = "index.html" if path in {"/", "/index.html"} else path.removeprefix("/")
            static_path = (STATIC_ROOT / static_name).resolve()
            try:
                static_path.relative_to(STATIC_ROOT.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not static_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_file(static_path)
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
        except (ManualFrameReviewError, OSError, json.JSONDecodeError) as exc:
            self._json({"status": "error", "code": "MANUAL-REVIEW-001", "message": str(exc)}, 500)

    def do_POST(self) -> None:
        try:
            if urlsplit(strip_route_prefix(self.path, "/manual")).path == "/api/manual-selections":
                self._json(self.workspace.save(self._body()))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (ManualFrameReviewError, OSError, json.JSONDecodeError) as exc:
            self._json({"status": "error", "code": "MANUAL-REVIEW-002", "message": str(exc)}, 400)


def main() -> int:
    parser = argparse.ArgumentParser(description="启动人工选帧与事件初标工作台")
    parser.add_argument("runtime_dir", type=Path, help="包含review_session.json、recording.mp4和contact_sheets的运行目录")
    parser.add_argument("--state-json", type=Path, required=True, help="人工候选持久化JSON")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not STATIC_ROOT.is_dir():
        parser.error(f"人工选帧前端尚未构建: {STATIC_ROOT}")
    ManualFrameReviewHandler.workspace = ManualFrameReviewWorkspace(
        runtime_dir=args.runtime_dir,
        state_path=args.state_json,
    )
    server = ThreadingHTTPServer((args.host, args.port), ManualFrameReviewHandler)
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
