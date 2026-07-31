#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis import (  # noqa: E402
    split_confirmed_v1_to_parallel_v2,
    write_json_atomic,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="将v1结果拆分成功能事件线和指标观察线")
    parser.add_argument("input", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    events, metrics = split_confirmed_v1_to_parallel_v2(payload)
    write_json_atomic(args.output_dir / "event_observations_v2.json", events)
    write_json_atomic(args.output_dir / "metric_observations_v2.json", metrics)
    print(json.dumps({
        "events": events["summary"],
        "metrics": metrics["summary"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
