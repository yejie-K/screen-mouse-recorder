# Screen Mouse Recorder

Windows desktop app for region screen recording plus structured mouse activity logs.

## Release Snapshot

The repository contains two independent local tools: `ScreenRecorder` and the beta
`JourneyAnalyzer`. The current source snapshot is `v2.2.0`. Read
[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) and
[docs/ARCHIVE_AND_RESUME.md](docs/ARCHIVE_AND_RESUME.md) before distributing or resuming work.

This is a source-available proprietary snapshot. Source visibility on GitHub
does not grant reuse or redistribution rights. Third-party obligations are summarized in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## 接手须知 / For agents & new contributors

开始改动前先读这两份文档，它们记录了"我们干到哪了"和代码是怎么分层的：

- [docs/DEV_LOG.md](docs/DEV_LOG.md) — 开发日志与交接记录（每次改动都要在这里追加一条）
- [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) — 模块边界与独立发布规则（改 import / 加依赖前必读）

## Run

Use Python 3.10+ on Windows:

```powershell
python -m pip install -r requirements.txt
python run.py
```

Or use the helper script:

```powershell
.\start_recorder.cmd
```

Useful commands:

```powershell
# Check Windows/Tkinter/FFmpeg/output directory readiness
.\start_recorder.cmd doctor

# Create config.json with default values
.\start_recorder.cmd init-config

# Regenerate mouse_summary.json and mouse_summary.xlsx for an existing session
.\start_recorder.cmd postprocess .\sessions\rec_20260609_153000

# Run a 2-second automated real recording self-test
.\start_recorder.cmd selftest-record --seconds 2

# Run a pause/resume segmented recording self-test
.\start_recorder.cmd selftest-pause --segment-seconds 0.8 --pause-seconds 0.5

# Estimate video contact-sheet output without generating files
.\start_recorder.cmd sample-frames .\sessions\rec_20260609_153000\recording.mp4 --interval 10 --cols 5 --rows 6 --estimate-only

# Generate contact sheets for a selected video range
.\start_recorder.cmd sample-frames .\sessions\rec_20260609_153000\recording.mp4 --start 00:00 --end 30:00 --interval 10 --cols 5 --rows 6

# OCR manually selected keyframes into JSON/XLSX/review images
.\start_recorder.cmd ocr-events .\selected_ocr_tiles.json --index .\keyframes_click_sheet_index.json --video .\recording.mp4

# Optional JSONL progress for integration with another local product
.\start_recorder.cmd ocr-events .\selected_ocr_tiles.json --index .\keyframes_click_sheet_index.json --video .\recording.mp4 --json-progress

# Start the polished manual frame-selection workbench (video + timeline + contact sheets)
python tools\serve_manual_frame_review.py .\review_runtime --state-json .\analysis\manual_frame_review.json --port 5173

# Convert an existing layout candidate into a reviewable region profile
python tools\convert_legacy_layout_profile.py .\layout_profile.json .\ocr_region_profile_draft.json --game-id demo --game-name 测试游戏

# Review and adjust OCR regions locally
python tools\serve_ocr_region_profile_review.py .\ocr_region_profile_draft.json .\ocr_layout --port 8767

# Review regions and expose the full-scan button with live progress
python tools\serve_ocr_region_profile_review.py .\ocr_region_profile.json .\ocr_layout --index-json .\keyframes_click_sheet_index.json --video .\recording.mp4 --scan-output .\region_scan_output --save-crops --port 8767

# Scan every indexed source frame using only confirmed cropped regions
python tools\scan_ocr_regions.py .\keyframes_click_sheet_index.json .\ocr_region_profile.json .\region_scan_output --video .\recording.mp4 --session-id <session_id> --json-progress

# Initialize one current journey workspace; all review pages use this manifest
python tools\prepare_journey_workspace.py <session_dir> <click_index.json> <workspace_dir> --game-id demo --game-name 测试游戏 --region-profile <ocr_region_profile.json>

# After region scanning, merge manual/automatic events and create both review packages
python tools\sync_journey_workspace.py <workspace_dir>

# Start the single-process workbench; every page uses the same port
python tools\serve_journey_workspace.py <workspace_dir> --port 8767
# /manual/  /regions/  /events/  /metrics/
# The shared Session selector can browse any local drive or folder.
# Prepared workspaces switch immediately; complete raw sessions can be prepared in the background.

# Windows shortcut: open the most recently used workspace and launch the browser
.\start_journey_analyzer.cmd
# The shared header's 退出 button stops the local server; closing only the browser tab does not.

# One command: preflight click workload, generate sheets, initialize workspace, and open workbenches
python tools\prepare_journey_run.py <session_dir> <run_dir> --game-id demo --game-name 测试游戏 --region-profile <ocr_region_profile.json> --serve

# Generate the confirmed XLSX, three charts, and Agent report
python tools\generate_journey_final.py <workspace_dir>

# Continue downstream without confirming candidates; output remains a clearly marked draft
python tools\generate_journey_preview.py <workspace_dir>
```

If PowerShell script execution is disabled, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_recorder.ps1 doctor
```

## Install / build / develop

Editable install (also gets dev tooling: pytest, ruff, mypy, pyinstaller):

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q          # run tests
ruff check src tests         # lint
screen-mouse-recorder --version
```

Optional local OCR support:

```powershell
python -m pip install -e ".[ocr]"
```

Build a standalone Windows executable (FFmpeg/Tesseract stay external, see `tools/README.md`):

```powershell
python scripts/build_exe.py   # -> dist/screen-mouse-recorder.exe
```

The single version source is `screen_mouse_recorder.__version__`; `pyproject.toml` reads it dynamically.
CI (`.github/workflows/ci.yml`) runs ruff + pytest on Windows for `main` and `dev/**`.


FFmpeg must be available as `ffmpeg.exe` on `PATH`, or configured in `config.json`:

```json
{
  "ffmpeg_path": "D:\\tools\\ffmpeg\\bin\\ffmpeg.exe"
}
```

## Main Features

- Fixed-size Tk desktop UI for recording and frame export.
- Region screen recording with mouse event, sampling, wheel, click, and drag logs.
- Optional local recording status banner.
- Automatic report output after recording stops.
- Frame export with interval sampling, click-keyframe sampling, crop preview, dense ranges, progress, and ETA.
- Local GitHub update check and fast-forward update prompt.
- Error reports with stable error codes under `logs/error_reports/`.

## Output

Each recording creates a unique folder under `sessions/`:

- `recording.mp4`
- `mouse_events.jsonl`
- `mouse_samples.jsonl`
- `session_meta.json`
- `mouse_summary.json`
- `mouse_summary.xlsx`
- `mouse_analysis.xlsx`
- `ffmpeg.log`

Recording also creates `auto_report/` after stop when enough mouse data is available:

- `report_summary.xlsx`
- `metrics.json`
- `chart_activity_timeline.png`
- `chart_click_heatmap.png`
- `chart_click_scatter.png`
- `chart_drag_duration.png`
- `keyframes_click_sheet.png`
- `keyframes_click_sheet_index.json`
- `analysis_handoff.json`

Frame export creates a folder under `frame_exports/` by default:

- `sheets/sheet_001_000000-000450.jpg`
- `index.csv`
- `preview.html`
- `manifest.json`

Manual keyframe OCR creates:

- `event_ocr_results.json`
- `event_ocr_results.xlsx`
- `ocr_review/*_source.jpg`
- `ocr_review/*_boxes.jpg`

The file contract and AI usage rules are documented in `docs/ocr_manual_event_workflow.md`.
Machine-readable contracts are under `schemas/selected_ocr_tiles.schema.json` and
`schemas/event_ocr_results.schema.json`.

The manual frame-selection UI is under `tools/manual_frame_review_web/`; its persisted
state uses `schemas/manual_frame_review.schema.json` instead of browser-only storage.
See `docs/manual_frame_review_workflow.md`. It preserves the existing video, timeline,
contact-sheet, keyboard, and manual-video-frame interactions and automatically adapts
manual contact-sheet selections to `selected_ocr_tiles.json`.

The recorder/analyzer Session contract is defined in
`docs/recorder_analysis_handoff_contract.md`. The end-to-end journey workflow is defined in
`docs/journey_pipeline_v2.md`.
The authoritative producer/consumer/version matrix is `docs/journey_contract_matrix.md`;
artifact versions are per-file contracts rather than one global product version.
Confirmed OCR regions are scanned against every extracted source frame using only
their cropped areas. Function events use `mode_tag + event_tag`; fixed metrics are
stored on a separate timeline. Contracts live under `schemas/ocr_region_profile.schema.json`,
`schemas/journey_event_observations.schema.json`, `schemas/journey_metric_observations.schema.json`,
and `schemas/journey_metric_review.schema.json`. Metric candidates are reviewed with
`tools/serve_metric_review.py`; the candidate file remains read-only while human decisions
and the reviewed output are written separately.

New journey runs are rooted at `journey_workspace.json`. The workspace verifies that
the scan fingerprint matches the current frame index and region profile, merges manual
high-confidence frames with automatic event candidates, and prevents stale review files
from being reused. Legacy migration tools remain available for audit but are not part of
the default workflow.

The unified workbench does not bind Session data to the source-code directory. Use the
shared `浏览` button to add a Session folder, a run directory containing `workspace/`,
or a library containing multiple runs from any accessible drive. The browser receives
only opaque workspace IDs. Recently selected roots are stored per Windows user at
`%LOCALAPPDATA%\ScreenMouseRecorder\journey_sessions.json`; this machine-local file is
not part of the source tree or release package. On another device, select the data folder
once again. Workspace artifacts continue to use relative paths, so moving the complete
workspace does not require preserving the original drive letter.

In the SC source layout, prefer selecting the timestamped directory that directly contains
`recording.mp4`, usually `sessions/recordings/<session_id>`. Selecting its `recordings` or
`sessions` parent is also supported and discovers all nested Sessions. The folder picker now
opens at `sessions/recordings` when that directory exists.

When a selected Session has a valid recorder handoff, the analyzer reuses its contact sheets
without extracting frames again. A native Session without a valid handoff is regenerated with
the same `CLICK_SUMMARY_V1` preset. A folder containing only `recording.mp4` remains usable in
plain-video mode, which creates fallback frames every 10 seconds without claiming click
semantics. Progress is shown in the shared browse control. The generated workspace is stored
at `<session>/analysis_output/journey_workspace/`; temporary files are removed after success
and retained only after failure for diagnosis.

For a new or long recording, `tools/prepare_journey_run.py` is the preferred entry. It
writes `preflight.json`, reuses the recorder handoff or generates sheets with the one official preset,
initializes the workspace, and can launch the review pages. The unified launcher watches
the workspace and automatically syncs/starts downstream review services after region OCR.

Journey semantic review uses a separate local browser workbench under
`tools/serve_journey_semantic_review.py`. It reads candidate/review JSON files,
serves evidence images only on `127.0.0.1`, and writes confirmed decisions plus an
optional per-game term profile. See `docs/journey_semantic_review_workflow.md`.

The manual frame-review frontend source lives in `tools/manual_frame_review_web/`.
Its small production `dist/` bundle is checked in because the Python server loads
it directly. To rebuild it, install the pinned dependencies from that directory
with pnpm and run `pnpm build`; never commit `node_modules/`.

The frame export tab can also generate click-driven keyframe sheets. Choose the click-keyframe
mode, select a session video, and the tool will use `mouse_events.jsonl` from the same session
to create `frame_exports/click_.../keyframes_click_sheet.png`.

## Notes

- The app records only mouse activity and selected screen pixels. It does not record keyboard input or audio.
- Mouse hooks require Windows. The UI starts on other platforms only for development, but recording is blocked.
- If FFmpeg is missing, the app shows a clear error before recording starts.
- Frame export works fully locally. It uses FFmpeg and Pillow only; it does not call any AI model.
- A custom session name can be entered before recording. The final folder keeps a timestamp prefix.
- Pause/resume records separate MP4 segments and combines them into `recording.mp4` when the session ends.
- After a recording ends, the selected region is cleared and the next session starts from a fresh region selection.
