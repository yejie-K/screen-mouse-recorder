#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_mouse_recorder.journey_analysis.event_review_bridge import (  # noqa: E402
    build_event_review_bundle,
)
from screen_mouse_recorder.journey_analysis.package import JourneyPackageError  # noqa: E402
from screen_mouse_recorder.journey_analysis.rules import JourneyRuleError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将event_observations_v2.json转换为功能事件复核工作台四件套",
    )
    parser.add_argument("event_observations", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--total-play-minutes", type=float)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        manifest = build_event_review_bundle(
            args.event_observations.resolve(),
            args.output_dir.resolve(),
            taxonomy_path=ROOT / "rules" / "gameplay_taxonomy_v0.1.json",
            emotion_rules_path=ROOT / "rules" / "emotion_rules_v0.1.json",
            total_play_time_ms=(
                max(0, int(round(args.total_play_minutes * 60_000)))
                if args.total_play_minutes is not None
                else None
            ),
            overwrite=args.overwrite,
        )
        print(json.dumps(manifest, ensure_ascii=False))
        return 0
    except (JourneyPackageError, JourneyRuleError, OSError, ValueError) as exc:
        print(f"JOURNEY-EVENT-BRIDGE-001: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
