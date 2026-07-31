# Keyframe Summary Event Plan

## Goal

Build a deduplicated keyframe contact sheet that can explain the same major gameplay events as the full MP4. The target is at least 90% agreement for meaningful event loops, using `sessions/20260610_163422` as the first validation sample.

## Event Boundary Rules

Events are split by complete player-system loops, not by every second.

Keep separate events when one of these starts:

- New tutorial objective, task step, or forced goal.
- Reward claim, reward popup, or task completion feedback.
- New interface layer such as character, skill, bag, chat, VIP, or shop.
- Combat start, combat result, boss/reward moment, or transition.
- Long automatic segment with visible state change and no player click.

Do not split continuous auto combat, auto pathing, loading, or waiting into per-second rows unless the visible state changes meaningfully.

## Keyframe Sources

The summary is built from multiple frame sources:

- `click_cluster`: user click keyframes after cluster dedupe.
- `visual_change`: extra frame inside a repeated click cluster when the image changes enough.
- `silent_gap`: compensation frame inserted when deduped clicks leave a long no-click interval.

Click frames remain the main structure. Silent gap frames are only a coverage guard for automatic gameplay.

## Deduplication Priority

1. Cluster nearby clicks by time and position.
2. Keep the representative frame for each cluster according to the active strategy.
3. Add visual-change frames only inside repeated clusters to avoid losing state transitions.
4. Add silent-gap compensation frames after dedupe when no click frame covers a long interval.

Official `CLICK_SUMMARY_V1` values:

- Cluster time: `1.5s`
- Cluster distance: `80px`
- Visual-change threshold: `22%`
- Silent gap threshold: `10s`
- Long silent gap threshold: `25s`
- Max silent frames per gap: `5`

These values are the single production preset shared by recorder auto-report and analyzer fallback generation. The normal UI exposes the result and generation state, not a second set of dedupe thresholds.

## Coverage Metrics

Each generated index should report:

- Raw click count.
- Kept frame count.
- Deduped click frame count.
- Silent compensation frame count.
- Maximum timeline gap before and after compensation.
- Count by selection reason.

The first practical success condition is:

- No long section of the MP4 is invisible in the contact sheet.
- Repeated click bursts are compressed strongly enough to review quickly.
- The contact sheet still shows reward, UI, combat, task, and transition outcomes.

## OCR Exploration

OCR is secondary. It should be tested on a small set of generated frames only. The first OCR goal is to identify whether common title/task/reward text can be extracted reliably enough to help label events; it should not block the keyframe summary pipeline.

The accepted manual-selection OCR contract is documented in `docs/ocr_manual_event_workflow.md`. Use that document as the source of truth for AI-readable event JSON, time-source priority, and review return markers.
