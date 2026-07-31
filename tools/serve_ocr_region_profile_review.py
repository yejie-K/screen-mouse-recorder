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
from screen_mouse_recorder.event_extraction import (  # noqa: E402
    RegionScanConfig,
    RegionScanJob,
    RegionProfileError,
    RegionProfileReviewWorkspace,
    RapidOCREngine,
)
from tools.ocr_runtime import load_rapidocr  # noqa: E402


STATIC_ROOT = ROOT / "tools" / "region_profile_review_web"


class RegionProfileHandler(BaseHTTPRequestHandler):
    workspace: RegionProfileReviewWorkspace
    scan_job: RegionScanJob | None = None

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
        if length <= 0 or length > 1_000_000:
            raise RegionProfileError("请求体为空或过大")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise RegionProfileError("请求体必须是对象")
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
            request_path = strip_route_prefix(self.path, "/regions")
            if request_path == "/workspace-shell.css":
                self._send_file(ROOT / "tools" / "workspace_shell.css")
                return
            if request_path == "/workspace-shell.js":
                self._send_file(ROOT / "tools" / "workspace_shell.js")
                return
            if request_path == "/api/state":
                self._json(self.workspace.state())
                return
            if request_path == "/api/scan-state":
                self._json(
                    self.scan_job.state()
                    if self.scan_job is not None
                    else {
                        "available": False,
                        "status": "unconfigured",
                        "done": 0,
                        "total": 0,
                        "message": "未配置正式扫描输入",
                        "error_code": "",
                        "error_message": "",
                        "result": {},
                        "output_dir": "",
                    }
                )
                return
            for prefix, preview in (("/api/preview/", True), ("/api/source/", False)):
                if request_path.startswith(prefix):
                    region_id = request_path.removeprefix(prefix).split("?", 1)[0]
                    path = self.workspace.evidence_for(region_id, preview=preview)
                    if path is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                    else:
                        self._send_file(path)
                    return
            if request_path.startswith("/api/manual-source/"):
                candidate_id = request_path.removeprefix("/api/manual-source/").split("?", 1)[0]
                path = self.workspace.manual_evidence_for(candidate_id)
                if path is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                else:
                    self._send_file(path)
                return
            static_name = "index.html" if request_path in {"/", "/index.html"} else request_path.removeprefix("/")
            if static_name not in {"index.html", "styles.css", "app.js"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_file(STATIC_ROOT / static_name)
        except (RegionProfileError, OSError, json.JSONDecodeError) as exc:
            self._json({"status": "error", "message": str(exc)}, 500)

    def do_POST(self) -> None:
        try:
            request_path = strip_route_prefix(self.path, "/regions")
            if request_path == "/api/region":
                self._json(self.workspace.save_region(self._body()))
                return
            if request_path == "/api/region/new":
                self._json(self.workspace.add_metric_region(self._body()))
                return
            if request_path == "/api/suggest-metric":
                self._json(self.workspace.suggest_metric(self._body()))
                return
            if request_path == "/api/scan":
                if self.scan_job is None:
                    raise RegionProfileError("当前工作台未配置正式扫描输入")
                if self.workspace.state()["profile_status"] != "complete":
                    raise RegionProfileError("区域配置完成后才能开始正式扫描")
                self._json(self.scan_job.start())
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (RegionProfileError, OSError, json.JSONDecodeError) as exc:
            self._json({"status": "error", "message": str(exc)}, 400)


def main() -> int:
    parser = argparse.ArgumentParser(description="启动OCR区域profile人工复核工作台")
    parser.add_argument("profile", type=Path)
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--index-json", type=Path, help="正式扫描使用的抽帧索引")
    parser.add_argument("--video", type=Path, help="索引缺少原始帧时使用的视频")
    parser.add_argument("--scan-output", type=Path, help="正式扫描输出目录")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--save-crops", action="store_true", help="保存局部OCR裁剪证据")
    parser.add_argument("--ocr-runtime", type=Path, help="可选OCR虚拟环境目录，用于本地开发运行")
    parser.add_argument("--manual-review", type=Path, help="人工选帧工作台保存的manual_frame_review.json")
    parser.add_argument("--session-id", default="", help="扫描结果所属Session；统一工作空间启动器会自动传入")
    args = parser.parse_args()
    ocr = load_rapidocr(
        ROOT,
        engine_factory=RapidOCREngine,
        explicit_runtime=args.ocr_runtime,
    )
    scan_values = (args.index_json, args.video, args.scan_output)
    if any(value is not None for value in scan_values) and not all(value is not None for value in scan_values):
        parser.error("--index-json、--video和--scan-output必须同时提供")
    RegionProfileHandler.scan_job = (
        RegionScanJob(RegionScanConfig(
            index_json=args.index_json,
            region_profile=args.profile,
            output_dir=args.scan_output,
            video_path=args.video,
            ffmpeg_path=args.ffmpeg,
            session_id=args.session_id,
            save_crops=args.save_crops,
        ))
        if all(value is not None for value in scan_values) and ocr.available
        else None
    )
    RegionProfileHandler.workspace = RegionProfileReviewWorkspace(
        profile_path=args.profile,
        evidence_root=args.evidence_root,
        manual_review_path=args.manual_review,
        video_path=args.video,
        manual_cache_dir=(args.scan_output / "manual_review_frames") if args.scan_output else None,
        ffmpeg_path=args.ffmpeg,
        ocr_engine=ocr.engine,
        ocr_status={"available": ocr.available, "source": ocr.source, "message": ocr.message},
    )
    server = ThreadingHTTPServer((args.host, args.port), RegionProfileHandler)
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
