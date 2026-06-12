from __future__ import annotations

from typing import Any

from .models import Region


DEFAULT_CALIBRATION_CLICK_TOLERANCE_PX = 80
DEFAULT_CALIBRATION_RESIDUAL_WARNING_PX = 20
MIN_CALIBRATION_POINTS = 5


def build_calibration_result(
    region: Region,
    clicks: list[dict[str, Any]],
    click_tolerance_px: int = DEFAULT_CALIBRATION_CLICK_TOLERANCE_PX,
    residual_warning_px: int = DEFAULT_CALIBRATION_RESIDUAL_WARNING_PX,
) -> dict[str, Any]:
    normalized_clicks: list[dict[str, Any]] = []
    for click in clicks:
        expected_x = int(click["expected_screen_x"])
        expected_y = int(click["expected_screen_y"])
        actual_x = int(click["actual_screen_x"])
        actual_y = int(click["actual_screen_y"])
        visual_x = int(click.get("tk_event_screen_x", actual_x))
        visual_y = int(click.get("tk_event_screen_y", actual_y))
        dx = actual_x - expected_x
        dy = actual_y - expected_y
        visual_dx = visual_x - expected_x
        visual_dy = visual_y - expected_y
        recorded_distance = (dx * dx + dy * dy) ** 0.5
        visual_distance = (visual_dx * visual_dx + visual_dy * visual_dy) ** 0.5
        expected_video_x = expected_x - region.screen_x
        expected_video_y = expected_y - region.screen_y
        visual_video_x = visual_x - region.screen_x
        visual_video_y = visual_y - region.screen_y
        recorded_region_x = actual_x - region.screen_x
        recorded_region_y = actual_y - region.screen_y
        normalized = dict(click)
        normalized.update(
            {
                "expected_screen_x": expected_x,
                "expected_screen_y": expected_y,
                "expected_video_x": expected_video_x,
                "expected_video_y": expected_video_y,
                "visual_video_x": visual_video_x,
                "visual_video_y": visual_video_y,
                "actual_screen_x": actual_x,
                "actual_screen_y": actual_y,
                "visual_screen_x": visual_x,
                "visual_screen_y": visual_y,
                "recorded_region_x": recorded_region_x,
                "recorded_region_y": recorded_region_y,
                "recorded_vs_visual_dx": recorded_region_x - visual_video_x,
                "recorded_vs_visual_dy": recorded_region_y - visual_video_y,
                "dx": dx,
                "dy": dy,
                "visual_dx": visual_dx,
                "visual_dy": visual_dy,
                "target_distance_px": round(visual_distance, 3),
                "recorded_distance_px": round(recorded_distance, 3),
                "distance_px": round(recorded_distance, 3),
                "inside_region": region.contains(actual_x, actual_y),
                "visual_inside_region": region.contains(visual_x, visual_y),
            }
        )
        normalized_clicks.append(normalized)

    distances = [item["target_distance_px"] for item in normalized_clicks]
    recorded_distances = [item["recorded_distance_px"] for item in normalized_clicks]
    inside_count = sum(1 for item in normalized_clicks if item["visual_inside_region"])
    actual_inside_count = sum(1 for item in normalized_clicks if item["inside_region"])
    failure_reasons: list[str] = []
    warnings: list[str] = []

    if len(normalized_clicks) != MIN_CALIBRATION_POINTS:
        failure_reasons.append(f"需要 {MIN_CALIBRATION_POINTS} 个检查点，当前只有 {len(normalized_clicks)} 个")
    outside_count = len(normalized_clicks) - inside_count
    if outside_count:
        failure_reasons.append(f"有 {outside_count} 个点不在录制区域内")
    far_points = [item for item in normalized_clicks if item["target_distance_px"] > click_tolerance_px]
    if far_points:
        labels = "、".join(str(item.get("label") or item.get("target_id")) for item in far_points)
        failure_reasons.append(f"{labels} 离目标点超过 {click_tolerance_px}px，可能点错检查区域")

    mapping = None
    fit_error = None
    residuals: list[float] = []
    if len(normalized_clicks) >= 3:
        try:
            mapping = fit_affine_mapping(normalized_clicks)
            for item in normalized_clicks:
                predicted_x, predicted_y = apply_affine_to_region_point(
                    mapping,
                    float(item["recorded_region_x"]),
                    float(item["recorded_region_y"]),
                )
                residual_x = predicted_x - float(item["visual_video_x"])
                residual_y = predicted_y - float(item["visual_video_y"])
                residual = (residual_x * residual_x + residual_y * residual_y) ** 0.5
                item.update(
                    {
                        "fit_video_x": round(predicted_x, 3),
                        "fit_video_y": round(predicted_y, 3),
                        "residual_x": round(residual_x, 3),
                        "residual_y": round(residual_y, 3),
                        "residual_px": round(residual, 3),
                    }
                )
                residuals.append(residual)
        except ValueError as exc:
            fit_error = str(exc)
            failure_reasons.append(f"无法计算对应关系：{fit_error}")
    else:
        fit_error = "not enough calibration points"
        failure_reasons.append("检查点不足，无法计算对应关系")

    max_distance = max(distances) if distances else 0.0
    avg_distance = sum(distances) / len(distances) if distances else 0.0
    max_recorded_distance = max(recorded_distances) if recorded_distances else 0.0
    avg_recorded_distance = sum(recorded_distances) / len(recorded_distances) if recorded_distances else 0.0
    max_residual = max(residuals) if residuals else 0.0
    avg_residual = sum(residuals) / len(residuals) if residuals else 0.0
    if mapping is not None and max_residual > residual_warning_px:
        warnings.append(f"记录坐标和视觉点击最大差异 {round(max_residual, 3)}px，建议重新检查")

    completed = not failure_reasons
    return {
        "schema_version": "1.2",
        "method": "five_point_correspondence_check",
        "region": region.to_dict(),
        "points": normalized_clicks,
        "click_tolerance_px": click_tolerance_px,
        "residual_warning_px": residual_warning_px,
        "max_target_distance_px": round(max_distance, 3),
        "avg_target_distance_px": round(avg_distance, 3),
        "max_recorded_distance_px": round(max_recorded_distance, 3),
        "avg_recorded_distance_px": round(avg_recorded_distance, 3),
        "max_error_px": round(max_recorded_distance, 3),
        "avg_error_px": round(avg_recorded_distance, 3),
        "max_residual_px": round(max_residual, 3),
        "avg_residual_px": round(avg_residual, 3),
        "inside_points": inside_count,
        "actual_inside_points": actual_inside_count,
        "completed": completed,
        "failure_reasons": failure_reasons,
        "warnings": warnings,
        "mapping": mapping,
    }


def fit_affine_mapping(points: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [[float(item["recorded_region_x"]), float(item["recorded_region_y"]), 1.0] for item in points]
    target_x = [float(item["visual_video_x"]) for item in points]
    target_y = [float(item["visual_video_y"]) for item in points]
    coeff_x = solve_least_squares_3(rows, target_x)
    coeff_y = solve_least_squares_3(rows, target_y)
    return {
        "method": "visual_affine_least_squares",
        "input": "recorded_region",
        "output": "visual_video_click",
        "applied_to_recording_rows": False,
        "matrix": [
            [round(coeff_x[0], 12), round(coeff_x[1], 12), round(coeff_x[2], 12)],
            [round(coeff_y[0], 12), round(coeff_y[1], 12), round(coeff_y[2], 12)],
        ],
        "description": (
            "Diagnostic only: visual_video_x = a * recorded_region_x + b * recorded_region_y + c; "
            "visual_video_y = d * recorded_region_x + e * recorded_region_y + f. "
            "Recording rows keep raw video coordinates."
        ),
    }


def solve_least_squares_3(rows: list[list[float]], values: list[float]) -> list[float]:
    normal = [[0.0, 0.0, 0.0] for _ in range(3)]
    rhs = [0.0, 0.0, 0.0]
    for row, value in zip(rows, values):
        for i in range(3):
            rhs[i] += row[i] * value
            for j in range(3):
                normal[i][j] += row[i] * row[j]
    return solve_3x3(normal, rhs)


def solve_3x3(matrix: list[list[float]], vector: list[float]) -> list[float]:
    augmented = [row[:] + [value] for row, value in zip(matrix, vector)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row_index: abs(augmented[row_index][column]))
        if abs(augmented[pivot][column]) < 1e-9:
            raise ValueError("calibration points are collinear or degenerate")
        if pivot != column:
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        for item_index in range(column, 4):
            augmented[column][item_index] /= divisor
        for row_index in range(3):
            if row_index == column:
                continue
            factor = augmented[row_index][column]
            for item_index in range(column, 4):
                augmented[row_index][item_index] -= factor * augmented[column][item_index]
    return [augmented[row][3] for row in range(3)]


def apply_affine_to_region_point(mapping: dict[str, Any], raw_region_x: float, raw_region_y: float) -> tuple[float, float]:
    matrix = mapping["matrix"]
    video_x = matrix[0][0] * raw_region_x + matrix[0][1] * raw_region_y + matrix[0][2]
    video_y = matrix[1][0] * raw_region_x + matrix[1][1] * raw_region_y + matrix[1][2]
    return video_x, video_y


def video_mapping(region: Region, x: int, y: int, calibration: dict[str, Any] | None) -> dict[str, Any]:
    raw_region_x = x - region.screen_x
    raw_region_y = y - region.screen_y
    method = "raw_video_region"
    applied = False
    video_x = float(raw_region_x)
    video_y = float(raw_region_y)

    calibrated_screen_x = region.screen_x + video_x
    calibrated_screen_y = region.screen_y + video_y
    inside_video_region = 0 <= video_x < region.width and 0 <= video_y < region.height
    return {
        "calibration_applied": applied,
        "calibration_method": method,
        "coordinate_check_completed": bool(calibration and calibration.get("completed")),
        "calibrated_screen_x": round(calibrated_screen_x, 3),
        "calibrated_screen_y": round(calibrated_screen_y, 3),
        "video_x": round(video_x, 3),
        "video_y": round(video_y, 3),
        "video_x_norm": round(video_x / region.width, 6) if region.width else None,
        "video_y_norm": round(video_y / region.height, 6) if region.height else None,
        "inside_video_region": inside_video_region,
    }
