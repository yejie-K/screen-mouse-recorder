# Screen Mouse Recorder

Windows desktop app for region screen recording plus structured mouse activity logs.

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

Frame export creates a folder under `frame_exports/` by default:

- `sheets/sheet_001_000000-000450.jpg`
- `index.csv`
- `preview.html`
- `manifest.json`

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
