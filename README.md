# Screen Mouse Recorder

Windows desktop MVP for region screen recording plus structured mouse activity logs.

## Run

Use any Python 3.10+ on Windows:

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
.\start_recorder.cmd postprocess .\sessions\20260609_153000

# Run a 2-second automated real recording self-test
.\start_recorder.cmd selftest-record --seconds 2

# Run a pause/resume segmented recording self-test
.\start_recorder.cmd selftest-pause --segment-seconds 0.8 --pause-seconds 0.5

# Estimate video contact-sheet output without generating files
.\start_recorder.cmd sample-frames .\sessions\20260609_153000\recording.mp4 --interval 10 --cols 5 --rows 6 --estimate-only

# Generate contact sheets for a selected video range
.\start_recorder.cmd sample-frames .\sessions\20260609_153000\recording.mp4 --start 00:00 --end 30:00 --interval 10 --cols 5 --rows 6
```

If you prefer PowerShell, use `powershell -ExecutionPolicy Bypass -File .\start_recorder.ps1 doctor`
when local script execution is disabled.

FFmpeg must be available as `ffmpeg.exe` on `PATH`, or configured in `config.json`:

```json
{
  "ffmpeg_path": "D:\\tools\\ffmpeg\\bin\\ffmpeg.exe"
}
```

## Output

Each recording creates a unique folder under `sessions/`:

- `recording.mp4`
- `mouse_events.jsonl`
- `mouse_samples.jsonl`
- `session_meta.json`
- `mouse_summary.json`
- `mouse_summary.xlsx`
- `ffmpeg.log`

Frame sampling creates a folder under `frame_sheets/` by default:

- `sheets/sheet_001_00-00-00_to_00-04-50.jpg`
- `index.csv`
- `report.html`
- `config.json`

The `抽帧拼图` tab can also generate click-driven keyframe sheets. Choose `点击关键帧`
as the mode, select a session video, and the tool will use `mouse_events.jsonl`
from the same session to create `analysis_output/click_keyframes.png`.

## Notes

- The app records only mouse activity and selected screen pixels. It does not record keyboard input or audio.
- Mouse hooks require Windows. The UI starts on other platforms only for development, but recording will be blocked.
- If FFmpeg is missing, the app will show a clear error before recording starts.
- The `抽帧拼图` tab works fully locally. It uses FFmpeg and Pillow only; it does not call any AI model.
- A custom session name can be entered before recording. The final folder keeps a timestamp prefix.
- Pause/resume records separate MP4 segments and combines them into `recording.mp4` when the session ends.
- After a recording ends, the selected region is cleared and the next session starts from a fresh region selection.
