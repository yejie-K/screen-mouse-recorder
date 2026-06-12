from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).resolve().parent
W, H = 1280, 820

BG = "#edf1f4"
PANEL = "#f8fafb"
PANEL_2 = "#eef3f6"
TEXT = "#17212b"
TEXT_2 = "#263238"
MUTED = "#60717d"
BORDER = "#c7d0d8"
SUBTLE = "#dfe7ec"
GREEN = "#1f9d55"
RED = "#d83b3b"
YELLOW = "#f0b429"
BLUE = "#1f6fb2"
DARK = "#263238"

FONT_PATHS = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\arial.ttf",
]
FONT_PATH = next((path for path in FONT_PATHS if Path(path).exists()), None)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        if FONT_PATH is None:
            raise OSError("No font")
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


F_TITLE = font(24)
F_H1 = font(20)
F_H2 = font(16)
F_BODY = font(14)
F_SMALL = font(12)
F_TIMER = font(48)


def rounded(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], fill: str, outline: str | None = None, radius: int = 8, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], value: str, fill: str = TEXT_2, font_obj: ImageFont.ImageFont = F_BODY, anchor: str | None = None) -> None:
    draw.text(xy, value, fill=fill, font=font_obj, anchor=anchor)


def pill(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, label: str, fill: str, fg: str = "white") -> None:
    rounded(draw, (x, y, x + w, y + h), fill, radius=6)
    text(draw, (x + w / 2, y + h / 2), label, fill=fg, font_obj=F_SMALL, anchor="mm")


def panel(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, title: str) -> None:
    rounded(draw, (x, y, x + w, y + h), PANEL, BORDER, radius=8)
    text(draw, (x + 14, y + 12), title, fill=TEXT, font_obj=F_H2)
    draw.line((x, y + 42, x + w, y + 42), fill=SUBTLE, width=1)


def button(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, label: str, fill: str, fg: str = "white") -> None:
    rounded(draw, (x, y, x + w, y + h), fill, radius=7)
    text(draw, (x + w / 2, y + h / 2), label, fill=fg, font_obj=F_BODY, anchor="mm")


def outline_button(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, label: str) -> None:
    rounded(draw, (x, y, x + w, y + h), "#ffffff", BORDER, radius=7)
    text(draw, (x + w / 2, y + h / 2), label, fill=TEXT_2, font_obj=F_BODY, anchor="mm")


def check_row(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, checked: bool = True) -> None:
    fill = GREEN if checked else "#ffffff"
    outline = GREEN if checked else BORDER
    rounded(draw, (x, y, x + 18, y + 18), fill, outline, radius=4)
    if checked:
        draw.line((x + 4, y + 9, x + 8, y + 13, x + 15, y + 5), fill="white", width=2)
    text(draw, (x + 26, y - 1), label, fill=TEXT_2, font_obj=F_BODY)
    rounded(draw, (x + 172, y, x + 190, y + 18), SUBTLE, radius=9)
    text(draw, (x + 181, y + 9), "i", fill=TEXT, font_obj=F_SMALL, anchor="mm")


def header(draw: ImageDraw.ImageDraw, selected: str = "record") -> None:
    text(draw, (32, 24), "Screen Mouse Recorder", fill=TEXT, font_obj=F_TITLE)
    text(draw, (300, 31), "v0.1", fill=MUTED, font_obj=F_BODY)
    text(draw, (872, 31), r"FFmpeg OK  ·  输出目录 D:\screen_capture\sessions", fill=MUTED, font_obj=F_SMALL)
    pill(draw, 1160, 22, 80, 28, "就绪", SUBTLE, TEXT_2)

    active = selected == "record"
    rounded(draw, (32, 72, 148, 110), DARK if active else SUBTLE, radius=6)
    text(draw, (90, 91), "录制", fill="white" if active else TEXT_2, font_obj=F_BODY, anchor="mm")

    active = selected == "analysis"
    rounded(draw, (156, 72, 272, 110), DARK if active else SUBTLE, radius=6)
    text(draw, (214, 91), "分析处理", fill="white" if active else TEXT_2, font_obj=F_BODY, anchor="mm")


def metric(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, label: str, value: str) -> None:
    rounded(draw, (x, y, x + w, y + 74), PANEL_2, BORDER, radius=7)
    text(draw, (x + w / 2, y + 24), value, fill=TEXT, font_obj=F_H1, anchor="mm")
    text(draw, (x + w / 2, y + 52), label, fill=MUTED, font_obj=F_SMALL, anchor="mm")


def mini_heatmap(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    rounded(draw, (x, y, x + w, y + h), "#ffffff", BORDER, radius=6)
    cell_w, cell_h = w / 12, h / 12
    for gy in range(12):
        for gx in range(12):
            val = max(0, 12 - abs(gx - 6) * 2 - abs(gy - 9) * 2)
            if val > 7:
                color = "#f0b429"
            elif val > 3:
                color = "#c7dfb9"
            else:
                color = "#8ecae6"
            draw.rectangle((x + gx * cell_w, y + gy * cell_h, x + (gx + 1) * cell_w + 1, y + (gy + 1) * cell_h + 1), fill=color)
    draw.rectangle((x, y, x + w, y + h), outline=TEXT, width=2)


def recording_workbench() -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    header(draw, "record")

    panel(draw, 32, 126, 320, 510, "流程")
    text(draw, (50, 188), "1 选择区域", fill=TEXT, font_obj=F_H2)
    rounded(draw, (50, 216, 334, 264), "#ffffff", BORDER, radius=6)
    text(draw, (64, 232), "x=1179 y=39   460x866", fill=TEXT_2, font_obj=F_BODY)
    outline_button(draw, 50, 276, 86, 34, "选择区域")
    outline_button(draw, 148, 276, 86, 34, "对应检查")
    outline_button(draw, 246, 276, 86, 34, "取消区域")
    text(draw, (50, 336), "2 坐标对应", fill=TEXT, font_obj=F_H2)
    rounded(draw, (50, 364, 334, 432), "#ffffff", BORDER, radius=6)
    text(draw, (64, 380), "已检查 · 平均差异 4.2px", fill=MUTED, font_obj=F_BODY)
    text(draw, (64, 404), "xlsx 使用视频原始坐标", fill=MUTED, font_obj=F_SMALL)
    text(draw, (50, 464), "3 开始录制", fill=TEXT, font_obj=F_H2)
    rounded(draw, (50, 492, 334, 570), "#ffffff", BORDER, radius=6)
    text(draw, (64, 510), "已就绪，可以开始录制", fill=GREEN, font_obj=F_BODY)
    text(draw, (64, 536), "确认记录选项后开始长时间测试", fill=MUTED, font_obj=F_SMALL)

    panel(draw, 376, 126, 350, 510, "录制控制")
    text(draw, (551, 214), "00:00.000", fill=TEXT, font_obj=F_TIMER, anchor="mm")
    text(draw, (551, 258), "当前录制时长", fill=MUTED, font_obj=F_SMALL, anchor="mm")
    rounded(draw, (406, 288, 696, 360), SUBTLE, radius=8)
    text(draw, (551, 324), "未开始录制", fill=TEXT_2, font_obj=F_H2, anchor="mm")
    button(draw, 406, 386, 84, 70, "▶", GREEN)
    button(draw, 508, 386, 84, 70, "Ⅱ", YELLOW, TEXT)
    button(draw, 610, 386, 84, 70, "■", RED)
    metric(draw, 406, 492, 88, "视频段", "0")
    metric(draw, 507, 492, 88, "暂停", "0")
    metric(draw, 608, 492, 88, "鼠标", "可见")

    panel(draw, 750, 126, 498, 510, "设置")
    text(draw, (768, 184), "输出目录", fill=TEXT_2, font_obj=F_BODY)
    rounded(draw, (838, 176, 1136, 208), "#ffffff", BORDER, radius=6)
    text(draw, (850, 185), r"D:\screen_capture\sessions", fill=MUTED, font_obj=F_SMALL)
    outline_button(draw, 1148, 176, 38, 32, "浏览")
    outline_button(draw, 1194, 176, 38, 32, "打开")
    text(draw, (768, 230), "Session 名称", fill=TEXT_2, font_obj=F_BODY)
    rounded(draw, (860, 222, 1232, 254), "#ffffff", BORDER, radius=6)
    text(draw, (874, 231), "第一次长时间测试", fill=TEXT_2, font_obj=F_SMALL)
    rounded(draw, (768, 284, 884, 322), DARK, radius=6)
    text(draw, (826, 303), "记录选项", fill="white", font_obj=F_BODY, anchor="mm")
    rounded(draw, (892, 284, 1008, 322), SUBTLE, radius=6)
    text(draw, (950, 303), "高级参数", fill=TEXT_2, font_obj=F_BODY, anchor="mm")
    check_row(draw, 772, 350, "记录区域外鼠标活动", False)
    check_row(draw, 1000, 350, "鼠标轨迹采样", True)
    check_row(draw, 772, 392, "点击事件识别", True)
    check_row(draw, 1000, 392, "滚轮事件记录", True)
    check_row(draw, 772, 434, "拖拽事件识别", True)
    check_row(draw, 1000, 434, "同步标记", False)
    check_row(draw, 772, 476, "状态提示栏", True)
    text(draw, (772, 548), "我已确认：应用将录制选定屏幕区域，并在本地记录鼠标活动数据。", fill=TEXT_2, font_obj=F_SMALL)

    panel(draw, 32, 660, 1216, 120, "最近 Session")
    text(draw, (50, 720), "输出", fill=TEXT_2, font_obj=F_BODY)
    text(draw, (110, 720), r"D:\screen_capture\sessions\20260610_163422", fill=TEXT, font_obj=F_BODY)
    text(draw, (110, 746), "事件 4728 · 采样 45266 · 点击 1382 · 滚轮 0 · 拖拽 16", fill=MUTED, font_obj=F_SMALL)
    outline_button(draw, 1040, 704, 86, 32, "打开文件夹")
    outline_button(draw, 1140, 704, 86, 32, "打开视频")
    text(draw, (50, 770), "mp4:OK · events:OK · samples:OK · xlsx:OK · analysis:OK · calibration:OK", fill=MUTED, font_obj=F_SMALL)
    image.save(OUT / "01_recording_workbench.png")


def analysis_import_empty() -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    header(draw, "analysis")

    panel(draw, 32, 126, 1216, 138, "导入")
    text(draw, (54, 190), "输入", fill=TEXT_2, font_obj=F_BODY)
    rounded(draw, (100, 180, 905, 216), "#ffffff", BORDER, radius=6)
    text(draw, (114, 190), "未选择", fill=MUTED, font_obj=F_BODY)
    button(draw, 922, 180, 92, 36, "选择 xlsx", BLUE)
    outline_button(draw, 1028, 180, 104, 36, "选择文件夹")
    text(draw, (54, 238), "输出", fill=TEXT_2, font_obj=F_BODY)
    rounded(draw, (100, 228, 1132, 256), "#ffffff", BORDER, radius=6)
    text(draw, (114, 235), "输出到导入文件夹下的 analysis_output", fill=MUTED, font_obj=F_SMALL)

    panel(draw, 32, 288, 1216, 142, "数据检查")
    rounded(draw, (54, 348, 292, 394), PANEL_2, BORDER, radius=7)
    text(draw, (70, 360), "等待导入", fill=TEXT, font_obj=F_H2)
    text(draw, (70, 382), "选择 xlsx 或 session 文件夹", fill=MUTED, font_obj=F_SMALL)
    for index, label in enumerate(["事件", "采样", "点击", "时长"]):
        x = 330 + index * 150
        rounded(draw, (x, 348, x + 130, 394), "#ffffff", BORDER, radius=7)
        text(draw, (x + 65, 362), "--", fill=MUTED, font_obj=F_H2, anchor="mm")
        text(draw, (x + 65, 383), label, fill=MUTED, font_obj=F_SMALL, anchor="mm")

    panel(draw, 32, 454, 1216, 326, "生成")
    button(draw, 54, 520, 128, 38, "生成分析报告", SUBTLE, TEXT_2)
    outline_button(draw, 196, 520, 86, 38, "打开输出")
    pill(draw, 1134, 524, 82, 28, "就绪", SUBTLE, TEXT_2)
    text(draw, (54, 598), "将输出以下文件", fill=TEXT, font_obj=F_H2)
    outputs = ["中文分析报告 xlsx", "视频比例热力图 PNG", "正方形热力矩阵 PNG", "点击分布图 PNG", "每分钟事件节奏图 PNG", "拖拽时长图 PNG"]
    for index, item in enumerate(outputs):
        x = 54 + (index % 3) * 360
        y = 638 + (index // 3) * 54
        rounded(draw, (x, y, x + 318, y + 40), "#ffffff", BORDER, radius=7)
        text(draw, (x + 14, y + 11), item, fill=TEXT_2, font_obj=F_BODY)
    image.save(OUT / "02_analysis_import_empty.png")


def analysis_generated() -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    header(draw, "analysis")

    panel(draw, 32, 126, 1216, 138, "导入")
    text(draw, (54, 190), "输入", fill=TEXT_2, font_obj=F_BODY)
    rounded(draw, (100, 180, 905, 216), "#ffffff", BORDER, radius=6)
    text(draw, (114, 190), r"D:\screen_capture\sessions\20260610_163422", fill=TEXT_2, font_obj=F_SMALL)
    button(draw, 922, 180, 92, 36, "选择 xlsx", BLUE)
    outline_button(draw, 1028, 180, 104, 36, "选择文件夹")
    text(draw, (54, 238), "输出", fill=TEXT_2, font_obj=F_BODY)
    rounded(draw, (100, 228, 1132, 256), "#ffffff", BORDER, radius=6)
    text(draw, (114, 235), r"D:\screen_capture\sessions\20260610_163422\analysis_output", fill=TEXT_2, font_obj=F_SMALL)

    panel(draw, 32, 288, 1216, 156, "数据检查")
    values = [("事件", "4728"), ("采样", "45266"), ("点击", "1382"), ("时长", "25.8分"), ("元数据", "OK")]
    for index, (label, value) in enumerate(values):
        x = 54 + index * 170
        rounded(draw, (x, 350, x + 146, 406), PANEL_2 if index == 0 else "#ffffff", BORDER, radius=7)
        text(draw, (x + 73, 368), value, fill=TEXT, font_obj=F_H2, anchor="mm")
        text(draw, (x + 73, 392), label, fill=MUTED, font_obj=F_SMALL, anchor="mm")
    pill(draw, 1056, 363, 92, 28, "数据可分析", GREEN)
    text(draw, (54, 420), "点击/分钟 53.55 · 底部三分之一点击占比 80.4% · 底部中区点击占比 54.5%", fill=MUTED, font_obj=F_SMALL)

    panel(draw, 32, 470, 1216, 310, "生成结果")
    button(draw, 54, 532, 128, 38, "重新生成报告", BLUE)
    outline_button(draw, 196, 532, 86, 38, "打开输出")
    pill(draw, 1134, 536, 82, 28, "已生成", GREEN)
    files = [
        ("mouse_behavior_report.xlsx", "中文分析报告"),
        ("click_heatmap_true_ratio.png", "视频比例热力图"),
        ("click_heatmap_square_matrix.png", "正方形热力矩阵"),
        ("activity_timeline.png", "每分钟事件节奏"),
        ("click_scatter.png", "点击位置分布"),
        ("drag_durations.png", "拖拽时长分布"),
    ]
    for index, (name, description) in enumerate(files):
        x = 54 + (index % 2) * 430
        y = 596 + (index // 2) * 52
        rounded(draw, (x, y, x + 392, y + 40), "#ffffff", BORDER, radius=7)
        pill(draw, x + 12, y + 9, 42, 22, "OK", GREEN)
        text(draw, (x + 66, y + 9), description, fill=TEXT, font_obj=F_BODY)
        text(draw, (x + 66, y + 26), name, fill=MUTED, font_obj=F_SMALL)
    mini_heatmap(draw, 980, 604, 190, 132)
    text(draw, (980, 746), "预览：最新点击热力图", fill=MUTED, font_obj=F_SMALL)
    image.save(OUT / "03_analysis_generated.png")


def report_preview() -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    header(draw, "analysis")
    panel(draw, 32, 126, 1216, 654, "报告预览")
    text(draw, (54, 188), "关键发现", fill=TEXT, font_obj=F_H1)
    findings = [
        ("80.4%", "点击集中在底部三分之一"),
        ("54.5%", "点击集中在底部中区"),
        ("53.55", "每分钟点击次数"),
        ("16", "拖拽次数"),
    ]
    for index, (value, label) in enumerate(findings):
        x = 54 + index * 210
        rounded(draw, (x, 230, x + 180, 332), "#ffffff", BORDER, radius=8)
        text(draw, (x + 90, 266), value, fill=TEXT, font_obj=F_H1, anchor="mm")
        text(draw, (x + 90, 300), label, fill=MUTED, font_obj=F_SMALL, anchor="mm")
    text(draw, (54, 380), "图表区域", fill=TEXT, font_obj=F_H1)
    mini_heatmap(draw, 54, 426, 250, 250)
    rounded(draw, (344, 426, 744, 676), "#ffffff", BORDER, radius=8)
    points = [(380, 620), (430, 560), (480, 590), (530, 535), (580, 610), (630, 500), (680, 545)]
    draw.line(points, fill=RED, width=4)
    for x, y in points:
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=RED)
    for index, bar_height in enumerate([190, 230, 120, 170, 90, 210, 160]):
        x = 372 + index * 44
        draw.rectangle((x, 676 - bar_height, x + 26, 676), fill="#8ecae6")
    text(draw, (370, 442), "每分钟事件与点击节奏", fill=TEXT, font_obj=F_BODY)
    rounded(draw, (784, 426, 1148, 676), "#ffffff", BORDER, radius=8)
    for index, bar_height in enumerate([60, 96, 72, 180, 75, 54, 130, 70, 50, 44, 84, 66, 120, 70, 58, 46]):
        x = 814 + index * 20
        draw.rectangle((x, 656 - bar_height, x + 12, 656), fill=GREEN)
    text(draw, (810, 442), "拖拽时长分布", fill=TEXT, font_obj=F_BODY)
    text(draw, (54, 716), "报告页保留图片输出，不把复杂图塞满应用主界面。应用只显示最新结果和打开入口。", fill=MUTED, font_obj=F_BODY)
    image.save(OUT / "04_report_preview.png")


if __name__ == "__main__":
    recording_workbench()
    analysis_import_empty()
    analysis_generated()
    report_preview()
    for path in sorted(OUT.glob("*.png")):
        print(path)
