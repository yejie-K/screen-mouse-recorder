from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from .models import ClickMarker, CropRegion, FramePlanEntry, FrameSamplerConfig


def _crop_and_resize(image: Image.Image, crop: CropRegion | None, thumb_width: int) -> Image.Image:
    image, _click_position = _prepare_frame_image(image, crop, thumb_width, None)
    return image

def _prepare_frame_image(
    image: Image.Image,
    crop: CropRegion | None,
    thumb_width: int,
    click_marker: ClickMarker | None,
) -> tuple[Image.Image, tuple[int, int] | None]:
    left, top, right, bottom = _crop_box(image, crop)
    click_position = _map_click_marker(click_marker, left, top, right, bottom, thumb_width)
    if (left, top, right, bottom) != (0, 0, image.width, image.height):
        image = image.crop((left, top, right, bottom))
    width = max(120, int(thumb_width))
    height = max(1, round(image.height * (width / image.width)))
    return image.resize((width, height), Image.Resampling.LANCZOS), click_position

def _crop_box(image: Image.Image, crop: CropRegion | None) -> tuple[int, int, int, int]:
    if crop is not None and crop.width > 0 and crop.height > 0:
        left = max(0, min(image.width - 1, crop.x))
        top = max(0, min(image.height - 1, crop.y))
        right = max(left + 1, min(image.width, left + crop.width))
        bottom = max(top + 1, min(image.height, top + crop.height))
        return left, top, right, bottom
    return 0, 0, image.width, image.height

def _map_click_marker(
    click_marker: ClickMarker | None,
    left: int,
    top: int,
    right: int,
    bottom: int,
    thumb_width: int,
) -> tuple[int, int] | None:
    if click_marker is None:
        return None
    if not (left <= click_marker.x <= right and top <= click_marker.y <= bottom):
        return None
    crop_width = max(1, right - left)
    scale = max(120, int(thumb_width)) / crop_width
    return round((click_marker.x - left) * scale), round((click_marker.y - top) * scale)

def _draw_overlay(image: Image.Image, entry: FramePlanEntry, config: FrameSamplerConfig) -> None:
    if not config.show_timestamp and not config.show_index:
        return
    draw = ImageDraw.Draw(image, "RGBA")
    font_size = max(13, min(24, image.width // 18))
    font = _load_font(font_size)
    lines: list[str] = []
    if config.show_index:
        lines.append(f"#{entry.index:03d}")
    if config.show_timestamp:
        lines.append(entry.timestamp)
    label = "  ".join(lines)
    bbox = draw.textbbox((0, 0), label, font=font)
    pad = max(5, font_size // 3)
    rect = (6, 6, 6 + (bbox[2] - bbox[0]) + pad * 2, 6 + (bbox[3] - bbox[1]) + pad * 2)
    fill = (0, 0, 0, 168 if not entry.is_dense else 196)
    draw.rounded_rectangle(rect, radius=5, fill=fill)
    draw.text((rect[0] + pad, rect[1] + pad), label, fill=(255, 255, 255, 255), font=font)
    if entry.is_dense:
        draw.rectangle((image.width - 8, 0, image.width, image.height), fill=(31, 111, 178, 190))

def _draw_click_marker(image: Image.Image, position: tuple[int, int] | None) -> None:
    if position is None:
        return
    x, y = position
    radius = max(7, min(14, image.width // 32))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((x - radius - 2, y - radius - 2, x + radius + 2, y + radius + 2), fill=(255, 255, 255, 230))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(216, 59, 59, 220))
    inner = max(3, radius // 2)
    draw.ellipse((x - inner, y - inner, x + inner, y + inner), fill=(255, 255, 255, 120))

def _compose_sheet(images: list[Image.Image], entries: list[FramePlanEntry], config: FrameSamplerConfig) -> Image.Image:
    cols = max(1, config.sheet_cols)
    rows = max(1, config.sheet_rows)
    gap = 8
    header_h = 46
    thumb_w = max(image.width for image in images)
    thumb_h = max(image.height for image in images)
    label_h = _frame_label_height(config, thumb_w)
    cell_h = thumb_h + label_h
    canvas_w = cols * thumb_w + (cols + 1) * gap
    canvas_h = header_h + rows * cell_h + (rows + 1) * gap
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#edf1f4")
    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(18)
    title = f"Sheet {entries[0].sheet_index:03d}  {entries[0].timestamp} - {entries[-1].timestamp}"
    draw.text((gap, 12), title, fill="#17212b", font=title_font)
    for image, entry in zip(images, entries):
        row = entry.sheet_row - 1
        col = entry.sheet_col - 1
        x = gap + col * (thumb_w + gap)
        y = header_h + gap + row * (cell_h + gap)
        canvas.paste(image, (x, y))
        _draw_frame_label(draw, x, y + thumb_h, thumb_w, label_h, entry, config)
    return canvas

def _frame_label_height(config: FrameSamplerConfig, thumb_width: int) -> int:
    if not config.show_timestamp and not config.show_index:
        return 0
    return max(22, min(34, max(1, int(thumb_width)) // 11))

def _frame_label_text(entry: FramePlanEntry, config: FrameSamplerConfig) -> str:
    lines: list[str] = []
    if config.show_index:
        lines.append(f"#{entry.index:03d}")
    if config.show_timestamp:
        lines.append(entry.timestamp)
    return "  ".join(lines)

def _fit_font_for_width(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, min_size: int = 9) -> ImageFont.ImageFont:
    for size in range(max(start_size, min_size), min_size - 1, -1):
        font = _load_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
    return _load_font(min_size)

def _draw_frame_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    entry: FramePlanEntry,
    config: FrameSamplerConfig,
) -> None:
    if height <= 0:
        return
    label = _frame_label_text(entry, config)
    bg = "#1f2933" if not entry.is_dense else "#1f6fb2"
    draw.rectangle((x, y, x + width, y + height), fill=bg)
    if not label:
        return
    pad_x = max(6, min(12, width // 24))
    font = _fit_font_for_width(draw, label, max(1, width - pad_x * 2), min(15, max(10, height - 8)))
    bbox = draw.textbbox((0, 0), label, font=font)
    text_y = y + max(1, (height - (bbox[3] - bbox[1])) // 2 - 1)
    draw.text((x + pad_x, text_y), label, fill="#ffffff", font=font)

def _load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "segoeui.ttf", "msyh.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()

