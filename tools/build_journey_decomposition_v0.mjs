// LEGACY: early one-off artifact generator. The Python workspace/final_product chain replaces this file.
// Keep for audit only; do not add new production behavior here.
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const EVENT_TYPE_LABELS = {
  new_feature_unlocked: "新功能开放",
  new_skill_unlocked: "新技能解锁",
  reward_popup: "奖励反馈",
  combat_power_snapshot: "战力观察",
  level_snapshot: "等级观察",
  task_progress: "任务推进",
  ui_opened: "界面打开",
  unknown: "待判断",
};

const CONTENT_COLUMNS = [
  "任务系统",
  "运营系统",
  "系统功能",
  "挖宝",
  "伙伴系统",
  "角色系统",
  "首领挑战",
  "聊天",
  "好友",
  "挑战",
  "主城",
  "邮箱",
];

const EMOTION_RULES = [
  ["EMO-PLAY-001", "玩法体验", "新玩法首次解锁 / 首次出现", 2, "首次新奇感强，若叠加眼前一亮等其他因素可升为+3"],
  ["EMO-PLAY-002", "玩法体验", "新玩法第二次出现（无新变化）", 1, "新鲜度下降，分值较首次减1"],
  ["EMO-PLAY-003", "玩法体验", "新功能开放，例如聊天、邮箱等无法立即获得深度体验的功能", 1, "有内容但无强烈冲击，中性偏正"],
  ["EMO-PLAY-004", "玩法体验", "发现创意惊喜的玩法，例如挖宝出现意外结果", 3, "惊喜通常是一瞬间的，不代表具备重复乐趣"],
  ["EMO-PLAY-005", "玩法体验", "长时间旁观 / 挂机等待", 0, "无主动交互，情绪无明显波动"],
  ["EMO-PLAY-006", "玩法体验", "复杂决策，例如阵容搭配思考", 2, "决策带来明确目标且可执行时给+2"],
  ["EMO-PLAY-007", "玩法体验", "简单决策，例如判断哪个装备战力更高", 1, "仅进行简单考虑"],
  ["EMO-PLAY-008", "玩法体验", "进入排行榜", 3, "形成强烈阶段反馈"],
  ["EMO-PLAY-009", "玩法体验", "完成超高难度的挑战", 3, "高难挑战成功"],
  ["EMO-PLAY-010", "玩法体验", "完成较高难度的挑战", 2, "较高难度挑战成功"],
  ["EMO-PLAY-011", "玩法体验", "解决不需要研究思考的简单问题，例如卡等级后继续挂机即可解决", 1, "自主解决但反馈不强"],
  ["EMO-PLAY-012", "玩法体验", "解决需要思考研究的困难问题，例如调整阵容战胜指定属性BOSS", 2, "自主探索带来成就感"],
  ["EMO-PLAY-013", "玩法体验", "任务繁琐，跑腿耗时过长", -1, "疲劳感上升，但未到厌烦"],
  ["EMO-PLAY-014", "玩法体验", "玩法重复、感到无聊", -1, "缺乏新意，但未产生强烈反感"],
  ["EMO-PLAY-015", "玩法体验", "微微受挫 / 卡点（卡关等）", -1, "难度陡增且无预期，首次挫败"],
  ["EMO-PLAY-016", "玩法体验", "强烈挫败感，想弃游（挑战失败且感到绝望）", -2, "连续受挫，负向累积"],
  ["EMO-PLAY-017", "玩法体验", "无任何引导（如无小红点），玩家迷茫", -1, "缺乏目标指向"],
  ["EMO-PLAY-018", "玩法体验", "社交排斥（无法组队、被踢出队伍、被嘲讽）", -2, "强烈人际负向"],
  ["EMO-PLAY-019", "玩法体验", "匹配到高战力对手，被碾压秒杀", -1, "不公平感和轻度挫败"],
  ["EMO-GROW-001", "成长反馈", "战力跳跃式增长（如飙升5倍以上）", 3, "数值飞跃带来强正反馈"],
  ["EMO-GROW-002", "成长反馈", "战力显著提升（明显增长2-5倍）", 2, "成长感知强烈"],
  ["EMO-GROW-003", "成长反馈", "战力提升（2倍以内）", 1, "有成长但不够惊喜"],
  ["EMO-GROW-004", "成长反馈", "获得超高价值、稀有装备/伙伴/坐骑，战力或外观显著改变", 3, "超高价值奖励；普通首次外观与战力提升需按实际强度复核"],
  ["EMO-GROW-005", "成长反馈", "获得高级物品，例如紫装或全紫装", 2, "高价值装备，兼具战力与价值反馈"],
  ["EMO-GROW-006", "成长反馈", "获得中等价值奖励", 1, "奖励品质中等"],
  ["EMO-GROW-007", "成长反馈", "获得大量低价值奖励（数量多）", 1, "数量形成明显爽感时可升为+2"],
  ["EMO-BIZ-001", "商业化", "物超所值的商业化，例如1元礼包、6元购买金色伙伴", 3, "极高性价比，远超预期"],
  ["EMO-BIZ-002", "商业化", "免费赠送VIP等级", 2, "免费获得明确商业化权益"],
  ["EMO-GOAL-001", "目标", "建立短期目标，例如收集全金色阵容", 1, "目标尚未实现，仅产生轻度期待"],
  ["EMO-OTHER-001", "其他", "游戏刚开始，有一定期待", 1, "开局惯性正期待"],
  ["EMO-OTHER-002", "其他", "眼前一亮 + 博彩乐趣，例如挖宝出现意外结果", 3, "创意组合带来强惊喜"],
  ["EMO-OTHER-003", "其他", "轻松 / 无感 / 无聊", 0, "情绪平稳"],
  ["EMO-OTHER-004", "其他", "困惑：高战力打不过低战力，但不理解原因", 0, "仅困惑但未受挫"],
  ["EMO-OTHER-005", "其他", "无明显事件（感受为——或……）", 0, "空值统一视为中性"],
  ["EMO-OTHER-006", "其他", "重大BUG或强制失败", -2, "预留极端负向规则"],
];

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    values[token.slice(2)] = argv[index + 1];
    index += 1;
  }
  for (const name of ["input", "output", "preview-dir"]) {
    if (!values[name]) throw new Error(`缺少参数 --${name}`);
  }
  return values;
}

function excelColumn(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function cleanText(value, limit = 500) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function extractLevel(event) {
  if (event.event_type === "level_snapshot") return event.event_name;
  const match = String(event.ocr_text ?? "").match(/(\d+)\s*级(?:\s*未转生)?/);
  return match ? match[0].replace(/\s+/g, "") : "";
}

function extractCombatPower(event) {
  return event.event_type === "combat_power_snapshot" ? event.event_name : "";
}

function systemFeedback(event) {
  if (event.event_type === "new_feature_unlocked") return `新功能开放：${event.event_name}`;
  if (event.event_type === "new_skill_unlocked") return `新技能解锁：${event.event_name}`;
  if (event.event_type === "level_snapshot") return `等级达到${event.event_name}`;
  if (event.event_type === "combat_power_snapshot") return `观察到战力${event.event_name}`;
  return cleanText(event.notes, 100);
}

function confirmationLabel(event) {
  const value = String(event.confirmation_source ?? event.review_status ?? "");
  if (value === "auto_confirmed") return "自动确认";
  if (value === "manual_confirmed" || value === "confirmed") return "人工确认";
  return value || "已确认";
}

function contentTags(event) {
  const tags = Object.fromEntries(CONTENT_COLUMNS.map((name) => [name, ""]));
  const name = String(event.event_name ?? "");
  if (event.event_type === "new_skill_unlocked") tags["角色系统"] = "new";
  if (/伙伴/.test(name)) tags["伙伴系统"] = "new";
  if (/BOSS|首领/i.test(name)) tags["首领挑战"] = "new";
  if (/仙术|仙品|宝石/.test(name)) tags["系统功能"] = "new";
  if (/副本|历练/.test(name)) tags["挑战"] = "new";
  return tags;
}

function gameplayType(name) {
  if (/BOSS|副本|历练/i.test(name)) return "PVE";
  return "系统&功能";
}

function teamRequirement(name) {
  if (/单人/.test(name)) return "单人";
  if (/多人/.test(name)) return "组队";
  return "";
}

function detectOutputs(text) {
  const source = String(text ?? "");
  const patterns = [
    ["元宝", /元宝\s*[xX×:]?\s*([\d.]+万?)/],
    ["灵气", /灵气\s*[xX×:]?\s*([\d.]+万?)/],
    ["铜钱", /(?:铜钱|铜)\s*[xX×:]?\s*([\d.]+万?)/],
    ["角色经验", /角色经验\s*[xX×:]?\s*([\d.]+万?)/],
  ];
  const result = {};
  for (const [label, pattern] of patterns) {
    const match = source.match(pattern);
    if (match) result[label] = match[1] ? `×${match[1]}` : "出现";
  }
  if (/获得[^。\n]{0,10}(?:装备|灵剑|宝石)/.test(source)) result["装备/材料"] = "OCR候选";
  if (/获得[^。\n]{0,10}伙伴/.test(source)) result["伙伴"] = "OCR候选";
  return result;
}

function mimeFor(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  if (extension === ".png") return "image/png";
  if (extension === ".webp") return "image/webp";
  return "image/jpeg";
}

async function imageDataUrl(filePath) {
  const bytes = await fs.readFile(filePath);
  return `data:${mimeFor(filePath)};base64,${bytes.toString("base64")}`;
}

function setWidth(sheet, columnIndex, lastRow, widthPx) {
  const column = excelColumn(columnIndex);
  sheet.getRange(`${column}1:${column}${lastRow}`).format.columnWidthPx = widthPx;
}

function styleTable(range, options = {}) {
  range.format = {
    font: { name: "Microsoft YaHei", size: options.fontSize ?? 10, color: options.fontColor ?? "#24313D" },
    fill: options.fill ?? "#FFFFFF",
    wrapText: true,
    verticalAlignment: "center",
    horizontalAlignment: options.align ?? "left",
    borders: { preset: "all", style: "thin", color: options.borderColor ?? "#C9D0D7" },
  };
}

function writeJourneySheet(workbook, events) {
  const sheet = workbook.worksheets.add("历程拆解表");
  sheet.showGridLines = false;
  const headers = [
    "视频序号", "原始时间戳", "修正时间段", "事件", "主线任务", "等级", "战力", "事件类型",
    "触发方式", "完成方式", "玩家行为/步骤", "系统反馈", "情绪值", "情绪说明",
    "截图1", "截图2", "截图3", "截图4", "截图5",
    ...CONTENT_COLUMNS,
    "证据事件ID", "OCR文本", "AI置信度", "确认方式", "复核状态", "备注",
  ];
  const lastColumn = excelColumn(headers.length - 1);
  const lastRow = 3 + events.length;

  sheet.mergeCells(`A1:${lastColumn}1`);
  sheet.getRange("A1").values = [["游戏历程拆解结果 V0"]];
  sheet.getRange(`A1:${lastColumn}1`).format = {
    fill: "#263238",
    font: { name: "Microsoft YaHei", size: 18, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "outside", style: "medium", color: "#263238" },
  };
  sheet.getRange(`A1:${lastColumn}1`).format.rowHeightPx = 38;

  const groups = [
    ["A2:N2", "事件历程", "#46689A"],
    ["O2:S2", "截图证据", "#5E8C4A"],
    ["T2:AE2", "内容解构", "#46689A"],
    ["AF2:AK2", "证据与复核", "#607D8B"],
  ];
  for (const [address, label, fill] of groups) {
    sheet.mergeCells(address);
    sheet.getRange(address).values = [[label]];
    sheet.getRange(address).format = {
      fill,
      font: { name: "Microsoft YaHei", size: 11, bold: true, color: "#FFFFFF" },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      borders: { preset: "all", style: "thin", color: "#D2D7DC" },
    };
  }
  sheet.getRange("A2:AK2").format.rowHeightPx = 25;

  sheet.getRange(`A3:${lastColumn}3`).values = [headers];
  styleTable(sheet.getRange(`A3:${lastColumn}3`), { fill: "#46689A", fontColor: "#FFFFFF", align: "center", fontSize: 10 });
  sheet.getRange(`A3:${lastColumn}3`).format.font.bold = true;
  sheet.getRange(`A3:${lastColumn}3`).format.rowHeightPx = 42;

  const rows = events.map((event) => {
    const tags = contentTags(event);
    return [
      "V001",
      event.timestamp,
      event.timestamp,
      event.event_name,
      "",
      extractLevel(event),
      extractCombatPower(event),
      EVENT_TYPE_LABELS[event.event_type] ?? event.event_type,
      "人工确认帧",
      "",
      "待语义补全",
      systemFeedback(event),
      "",
      "待匹配情绪规则",
      "", "", "", "", "",
      ...CONTENT_COLUMNS.map((name) => tags[name]),
      event.event_id,
      cleanText(event.ocr_text),
      typeof event.confidence === "number" ? event.confidence : "",
      confirmationLabel(event),
      "已确认",
      cleanText(event.notes, 120),
    ];
  });
  sheet.getRange(`A4:${lastColumn}${lastRow}`).values = rows;
  styleTable(sheet.getRange(`A4:${lastColumn}${lastRow}`));
  sheet.getRange(`A4:${lastColumn}${lastRow}`).format.rowHeightPx = 198;
  sheet.getRange(`A4:N${lastRow}`).format.verticalAlignment = "top";
  sheet.getRange(`T4:AE${lastRow}`).format.horizontalAlignment = "center";
  sheet.getRange(`AH4:AH${lastRow}`).format.numberFormat = "0.00";
  sheet.getRange(`M4:M${lastRow}`).dataValidation = { rule: { type: "list", values: [-2, -1, 0, 1, 2, 3] } };
  sheet.getRange(`AJ4:AJ${lastRow}`).format.fill = "#E5F3EA";
  sheet.getRange(`N4:N${lastRow}`).format.fill = "#FFF7DD";
  sheet.getRange(`K4:K${lastRow}`).format.fill = "#FFF7DD";

  const widths = [
    72, 94, 100, 115, 100, 88, 88, 96, 92, 92, 175, 190, 66, 190,
    112, 112, 112, 112, 112,
    ...CONTENT_COLUMNS.map(() => 72),
    150, 330, 78, 92, 82, 150,
  ];
  widths.forEach((width, index) => setWidth(sheet, index, lastRow, width));

  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(4);
  return { sheet, lastRow, headers };
}

async function embedJourneyImages(sheet, events) {
  for (let index = 0; index < events.length; index += 1) {
    const event = events[index];
    const row = 3 + index;
    const images = [event.source_image, event.review_image].filter(Boolean);
    for (let imageIndex = 0; imageIndex < images.length; imageIndex += 1) {
      try {
        const dataUrl = await imageDataUrl(images[imageIndex]);
        sheet.images.add({
          dataUrl,
          anchor: {
            from: { row, col: 14 + imageIndex, rowOffsetPx: 5, colOffsetPx: 5 },
            extent: { widthPx: 102, heightPx: 183 },
          },
        });
      } catch (error) {
        sheet.getCell(row, 14 + imageIndex).values = [[`图片读取失败：${path.basename(images[imageIndex])}`]];
      }
    }
  }
}

function buildGameplayRows(events) {
  const features = events.filter((event) => event.event_type === "new_feature_unlocked");
  const outputMaps = features.map((event) => detectOutputs(event.ocr_text));
  const outputColumns = [...new Set(outputMaps.flatMap((item) => Object.keys(item)))];
  if (outputColumns.length === 0) outputColumns.push("待识别产出");
  const rows = features.map((event, index) => [
    event.event_name,
    event.timestamp,
    extractLevel(event),
    teamRequirement(event.event_name),
    "",
    gameplayType(event.event_name),
    ...outputColumns.map((name) => outputMaps[index][name] ?? ""),
    event.event_id,
    "OCR候选，需结合玩法规则复核",
  ]);
  return { rows, outputColumns };
}

function writeGameplaySheet(workbook, events) {
  const { rows, outputColumns } = buildGameplayRows(events);
  const sheet = workbook.worksheets.add("玩法信息表");
  sheet.showGridLines = false;
  const headers = ["玩法/系统", "开启时间", "开启条件", "组队要求", "限时要求", "玩法类型", ...outputColumns, "证据事件ID", "备注"];
  const lastColumn = excelColumn(headers.length - 1);
  const lastRow = 3 + rows.length;
  const outputEnd = excelColumn(5 + outputColumns.length);

  sheet.mergeCells(`A1:${lastColumn}1`);
  sheet.getRange("A1").values = [["玩法信息与玩法产出 V0"]];
  sheet.getRange(`A1:${lastColumn}1`).format = {
    fill: "#263238",
    font: { name: "Microsoft YaHei", size: 17, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "outside", style: "medium", color: "#263238" },
  };
  sheet.getRange(`A1:${lastColumn}1`).format.rowHeightPx = 38;

  sheet.mergeCells("A2:F2");
  sheet.getRange("A2:F2").values = [["玩法信息（固定字段）"]];
  sheet.getRange("A2:F2").format = {
    fill: "#3D7D61",
    font: { name: "Microsoft YaHei", size: 11, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#C9D0D7" },
  };
  sheet.mergeCells(`G2:${outputEnd}2`);
  sheet.getRange(`G2:${outputEnd}2`).values = [["玩法产出（按当前游戏动态生成）"]];
  sheet.getRange(`G2:${outputEnd}2`).format = {
    fill: "#46689A",
    font: { name: "Microsoft YaHei", size: 11, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#C9D0D7" },
  };
  const evidenceStart = excelColumn(6 + outputColumns.length);
  sheet.mergeCells(`${evidenceStart}2:${lastColumn}2`);
  sheet.getRange(`${evidenceStart}2:${lastColumn}2`).values = [["证据与说明"]];
  sheet.getRange(`${evidenceStart}2:${lastColumn}2`).format = {
    fill: "#607D8B",
    font: { name: "Microsoft YaHei", size: 11, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#C9D0D7" },
  };

  sheet.getRange(`A3:${lastColumn}3`).values = [headers];
  styleTable(sheet.getRange(`A3:${lastColumn}3`), { fill: "#46689A", fontColor: "#FFFFFF", align: "center" });
  sheet.getRange(`A3:${lastColumn}3`).format.font.bold = true;
  sheet.getRange(`A4:${lastColumn}${lastRow}`).values = rows;
  styleTable(sheet.getRange(`A4:${lastColumn}${lastRow}`));
  sheet.getRange(`A4:F${lastRow}`).format.fill = "#F1F7EE";
  sheet.getRange(`G4:${outputEnd}${lastRow}`).format.fill = "#FFF7DD";
  sheet.getRange(`G4:${outputEnd}${lastRow}`).format.horizontalAlignment = "center";
  sheet.getRange(`A4:${lastColumn}${lastRow}`).format.rowHeightPx = 44;
  sheet.getRange(`A1:${lastColumn}3`).format.rowHeightPx = 30;

  const widths = [150, 92, 100, 92, 92, 96, ...outputColumns.map(() => 100), 155, 230];
  widths.forEach((width, index) => setWidth(sheet, index, lastRow, width));
  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(1);
  return { sheet, lastColumn, lastRow, outputColumns };
}

function writeEmotionRulesSheet(workbook) {
  const sheet = workbook.worksheets.add("情绪规则表");
  sheet.showGridLines = false;
  const lastRow = 6 + EMOTION_RULES.length;
  sheet.mergeCells("A1:F1");
  sheet.getRange("A1").values = [["情绪评分规则库 V0"]];
  sheet.getRange("A1:F1").format = {
    fill: "#263238",
    font: { name: "Microsoft YaHei", size: 17, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "outside", style: "medium", color: "#263238" },
  };
  const notes = [
    ["匹配原则", "先定位事件类型，再对照典型事件描述中最接近的样例，取用对应分值。"],
    ["特殊叠加", "同一事件包含多个元素时取最高分；出现创意+高价值时直接给+3。"],
    ["重复内容", "同一玩法第二次出现且无新增价值时，默认比首次低1分。"],
  ];
  notes.forEach(([label, text], index) => {
    const row = 2 + index;
    sheet.getRange(`A${row}`).values = [[label]];
    sheet.mergeCells(`B${row}:F${row}`);
    sheet.getRange(`B${row}:F${row}`).values = [[text]];
  });
  styleTable(sheet.getRange("A2:F4"), { fill: "#F3F6F8" });
  sheet.getRange("A2:A4").format.font.bold = true;
  sheet.getRange("A2:F4").format.rowHeightPx = 32;

  const headers = ["规则ID", "事件类型", "典型事件描述（示例）", "情绪分值", "备注/判定要点", "状态"];
  sheet.getRange("A6:F6").values = [headers];
  styleTable(sheet.getRange("A6:F6"), { fill: "#46689A", fontColor: "#FFFFFF", align: "center" });
  sheet.getRange("A6:F6").format.font.bold = true;
  const rows = EMOTION_RULES.map((rule) => [...rule, "启用"]);
  sheet.getRange(`A7:F${lastRow}`).values = rows;
  styleTable(sheet.getRange(`A7:F${lastRow}`));
  sheet.getRange(`D7:D${lastRow}`).format.horizontalAlignment = "center";
  sheet.getRange(`F7:F${lastRow}`).format.horizontalAlignment = "center";
  sheet.getRange(`A7:F${lastRow}`).format.rowHeightPx = 46;
  for (let index = 0; index < EMOTION_RULES.length; index += 1) {
    const row = 7 + index;
    const score = EMOTION_RULES[index][3];
    const fill = score >= 2 ? "#DFF1E6" : score < 0 ? "#FBE3E3" : score === 0 ? "#ECEFF2" : "#FFF3D1";
    sheet.getRange(`D${row}`).format.fill = fill;
    sheet.getRange(`D${row}`).format.font.bold = true;
  }
  [105, 95, 410, 78, 340, 72].forEach((width, index) => setWidth(sheet, index, lastRow, width));
  sheet.freezePanes.freezeRows(6);
  return { sheet, lastRow };
}

function writeEvidenceSheet(workbook, events, inputPath) {
  const sheet = workbook.worksheets.add("证据索引");
  sheet.showGridLines = false;
  const headers = ["事件ID", "时间戳", "事件名称", "原始截图文件", "框选截图文件", "拼图文件", "拼图行", "拼图列", "OCR文本", "来源结果文件"];
  const rows = events.map((event) => [
    event.event_id,
    event.timestamp,
    event.event_name,
    path.basename(event.source_image ?? ""),
    path.basename(event.review_image ?? ""),
    event.contact_sheet ?? "",
    event.sheet_row ?? "",
    event.sheet_col ?? "",
    cleanText(event.ocr_text, 1000),
    path.basename(inputPath),
  ]);
  const lastRow = 1 + rows.length;
  sheet.getRange("A1:J1").values = [headers];
  styleTable(sheet.getRange("A1:J1"), { fill: "#607D8B", fontColor: "#FFFFFF", align: "center" });
  sheet.getRange("A1:J1").format.font.bold = true;
  sheet.getRange(`A2:J${lastRow}`).values = rows;
  styleTable(sheet.getRange(`A2:J${lastRow}`));
  sheet.getRange(`A2:J${lastRow}`).format.rowHeightPx = 48;
  [155, 100, 115, 190, 190, 155, 70, 70, 420, 230].forEach((width, index) => setWidth(sheet, index, lastRow, width));
  sheet.freezePanes.freezeRows(1);
  return { sheet, lastRow };
}

async function savePreview(workbook, options, outputPath) {
  const preview = await workbook.render({ ...options, format: "png" });
  await fs.writeFile(outputPath, new Uint8Array(await preview.arrayBuffer()));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const inputPath = path.resolve(args.input);
  const outputPath = path.resolve(args.output);
  const previewDir = path.resolve(args["preview-dir"]);
  const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
  if (!Array.isArray(payload.events) || payload.events.length === 0) throw new Error("输入文件没有确认事件");
  const events = [...payload.events].sort((left, right) => left.time_ms - right.time_ms);

  const workbook = Workbook.create();
  const journey = writeJourneySheet(workbook, events);
  await embedJourneyImages(journey.sheet, events);
  const gameplay = writeGameplaySheet(workbook, events);
  const emotion = writeEmotionRulesSheet(workbook);
  const evidence = writeEvidenceSheet(workbook, events, inputPath);

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.mkdir(previewDir, { recursive: true });

  const inspection = await workbook.inspect({
    kind: "workbook,sheet,drawing",
    maxChars: 8000,
    tableMaxRows: 4,
    tableMaxCols: 8,
  });
  await fs.writeFile(path.join(previewDir, "inspection.ndjson"), inspection.ndjson, "utf8");

  await savePreview(workbook, { sheetName: "历程拆解表", range: "A1:S6", scale: 0.8 }, path.join(previewDir, "journey_left.png"));
  await savePreview(workbook, { sheetName: "历程拆解表", range: "T1:AK6", scale: 0.9 }, path.join(previewDir, "journey_right.png"));
  await savePreview(workbook, { sheetName: "玩法信息表", range: `A1:${gameplay.lastColumn}${gameplay.lastRow}`, scale: 1 }, path.join(previewDir, "gameplay.png"));
  await savePreview(workbook, { sheetName: "情绪规则表", range: `A1:F${emotion.lastRow}`, scale: 0.8 }, path.join(previewDir, "emotion_rules.png"));
  await savePreview(workbook, { sheetName: "证据索引", range: "A1:J8", scale: 0.8 }, path.join(previewDir, "evidence.png"));

  const exported = await SpreadsheetFile.exportXlsx(workbook);
  await exported.save(outputPath);
  console.log(JSON.stringify({
    output: outputPath,
    event_count: events.length,
    embedded_image_count: events.length * 2,
    gameplay_rows: gameplay.lastRow - 3,
    dynamic_output_columns: gameplay.outputColumns,
    emotion_rule_count: EMOTION_RULES.length,
  }, null, 2));
}

main().catch((error) => {
  console.error(error?.stack ?? String(error));
  process.exitCode = 1;
});
