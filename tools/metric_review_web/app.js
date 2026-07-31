const STATUS = { pending: "待复核", confirmed: "已确认", excluded: "已排除" };
let state = null;
let selectedId = null;
let activeFilter = "pending";
const BASE_PATH = "/metrics";

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

async function api(path, options = {}) {
  const response = await fetch(`${BASE_PATH}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message || "请求失败");
  return payload;
}

function metricLabel(key) {
  return state?.metric_keys.find((item) => item.value === key)?.label || key || "待判断";
}
function formatValue(metric) {
  const value = metric?.parsed_value;
  return value === null || value === undefined || value === "" ? "未解析" : `${value}${metric.unit || ""}`;
}
function currentMetric() { return state?.metrics.find((metric) => metric.observation_id === selectedId) || null; }
function filteredMetrics() {
  const query = $("#search").value.trim().toLowerCase();
  return (state?.metrics || []).filter((metric) => {
    const statusMatch = activeFilter === "all"
      || metric.status === activeFilter
      || (activeFilter === "flagged" && metric.flags.length > 0 && metric.status === "pending");
    const text = `${metric.timestamp} ${metric.ocr_text} ${metric.raw_text} ${metric.region_id} ${metricLabel(metric.metric_key)}`.toLowerCase();
    return statusMatch && (!query || text.includes(query));
  });
}

function renderSummary() {
  const s = state.summary;
  $("#summary").innerHTML = [[s.pending,"待复核"],[s.confirmed,"已确认"],[s.excluded,"已排除"],[s.flagged,"重点"]]
    .map(([value,label]) => `<div class="summary-item"><strong>${value}</strong><span>${label}</span></div>`).join("");
  const sessionId = state.session.session_id || "未知session";
  $("#session").textContent = `${sessionId} · ${state.scan_scope || "未知扫描范围"}`;
}

function renderList() {
  const metrics = filteredMetrics();
  $("#metric-count").textContent = `${metrics.length} 条指标`;
  $("#metric-list").innerHTML = metrics.map((metric) => `<button class="metric-row${metric.observation_id===selectedId?" selected":""}" data-id="${escapeHtml(metric.observation_id)}">
    <span><span class="name">${escapeHtml(metricLabel(metric.metric_key))} · ${escapeHtml(formatValue(metric))}</span><small>${escapeHtml(metric.timestamp || "无时间")} · ${escapeHtml(metric.raw_text || "无OCR")}</small></span>
    <span class="row-mark ${metric.status}" title="${STATUS[metric.status]}"></span>
  </button>`).join("");
  document.querySelectorAll(".metric-row").forEach((row) => row.addEventListener("click", () => selectMetric(row.dataset.id)));
  if (!metrics.some((metric) => metric.observation_id === selectedId)) selectedId = metrics[0]?.observation_id || null;
}

function optionHtml(values, selected) {
  return values.map((item) => `<option value="${escapeHtml(item.value)}" ${item.value===selected?"selected":""}>${escapeHtml(item.label)}</option>`).join("");
}
function renderDetail() {
  const metric = currentMetric();
  if (!metric) {
    $("#metric-title").textContent = "当前筛选没有指标";
    $("#evidence-image").hidden = true;
    $("#evidence-empty").hidden = false;
    return;
  }
  $("#metric-title").textContent = `${metricLabel(metric.metric_key)} · ${formatValue(metric)}`;
  $("#metric-kicker").textContent = metric.observation_id;
  $("#metric-status").textContent = STATUS[metric.status];
  $("#metric-status").className = `status-badge ${metric.status}`;
  $("#flags").textContent = metric.flags.join("；");
  $("#evidence-image").src = metric.evidence_url ? `${BASE_PATH}${metric.evidence_url}?t=${Date.now()}` : "";
  $("#evidence-image").hidden = !metric.evidence_url;
  $("#evidence-empty").hidden = Boolean(metric.evidence_url);
  $("#time").textContent = metric.timestamp || `${Math.round((metric.time_ms || 0) / 1000)}s`;
  $("#frames").textContent = String(metric.occurrence_frame_count || 1);
  $("#confidence").textContent = typeof metric.confidence === "number" ? `${Math.round(metric.confidence * 100)}%` : "未提供";
  $("#region").textContent = metric.region_id || "旧数据未记录";
  $("#ocr-text").textContent = metric.ocr_text || metric.raw_text || "无";
  $("#metric-key").innerHTML = optionHtml(state.metric_keys, metric.metric_key);
  $("#parsed-value").value = metric.parsed_value ?? "";
  $("#rebirth").value = metric.parsed_fields?.rebirth ?? "";
  $("#level").value = metric.parsed_fields?.level ?? "";
  $("#unit").value = metric.unit || "";
  $("#original-value").textContent = `${metric.raw_text || "无"} → ${formatValue(metric)}`;
  $("#review-note").value = metric.review_note || "";
  toggleLevelFields();
  const list = filteredMetrics();
  const index = list.findIndex((item) => item.observation_id === selectedId);
  $("#position").textContent = `${index + 1} / ${list.length}`;
  $("#previous").disabled = index <= 0;
  $("#next").disabled = index < 0 || index >= list.length - 1;
  showMessage("");
}

function selectMetric(id) { selectedId = id; renderList(); renderDetail(); }
function move(delta) {
  const list = filteredMetrics();
  const index = list.findIndex((metric) => metric.observation_id === selectedId);
  if (list[index + delta]) selectMetric(list[index + delta].observation_id);
}
function showMessage(text, kind="") { $("#message").textContent = text; $("#message").className = `message ${kind}`; }
function toggleLevelFields() { $("#level-fields").hidden = $("#metric-key").value !== "level_rebirth"; }

function parsedOverrides() {
  const metricKey = $("#metric-key").value;
  const text = $("#parsed-value").value.trim();
  const unit = $("#unit").value.trim();
  if (metricKey === "level_rebirth") {
    const rebirthText = $("#rebirth").value.trim();
    const levelText = $("#level").value.trim();
    const fields = {};
    if (rebirthText) fields.rebirth = Number(rebirthText);
    if (levelText) fields.level = Number(levelText);
    const display = `${fields.rebirth !== undefined ? `${fields.rebirth}转` : ""}${fields.level !== undefined ? `${fields.level}级` : ""}` || text;
    return { metric_key: metricKey, parsed_value: display || null, parsed_fields: fields, unit };
  }
  if (!text) return { metric_key: metricKey, parsed_value: null, parsed_fields: {}, unit };
  const numeric = Number(text.replace(/,/g, ""));
  if (!Number.isFinite(numeric) && metricKey !== "unknown") throw new Error("该指标需要填写数字确认值");
  return { metric_key: metricKey, parsed_value: Number.isFinite(numeric) ? numeric : text, parsed_fields: {}, unit };
}

async function save(decision) {
  const metric = currentMetric();
  if (!metric) return;
  const reviewer = $("#reviewer").value.trim();
  if (["confirmed","excluded"].includes(decision) && !reviewer) { showMessage("请填写复核人", "error"); return; }
  try {
    const overrides = parsedOverrides();
    state = await api("/api/decision", { method: "POST", body: JSON.stringify({
      observation_id: metric.observation_id,
      decision,
      reviewer,
      overrides,
      review_note: $("#review-note").value,
    }) });
    localStorage.setItem("metric-reviewer", reviewer);
    renderAll();
    showMessage(`已保存为${STATUS[decision]}`, "success");
  } catch (error) { showMessage(error.message, "error"); }
}

async function bulkConfirm() {
  const reviewer = $("#reviewer").value.trim();
  if (!reviewer) { showMessage("请填写复核人", "error"); return; }
  const ids = filteredMetrics().filter((metric) => metric.status === "pending" && metric.parsed_value !== null && metric.flags.length === 0).map((metric) => metric.observation_id);
  if (!ids.length) { showMessage("当前列表没有可批量确认的已解析指标", "error"); return; }
  try {
    state = await api("/api/bulk-confirm", { method: "POST", body: JSON.stringify({ observation_ids: ids, reviewer }) });
    localStorage.setItem("metric-reviewer", reviewer);
    renderAll();
    showMessage(`已确认 ${ids.length} 条`, "success");
  } catch (error) { showMessage(error.message, "error"); }
}

function renderAll() { renderSummary(); renderList(); renderDetail(); }

document.querySelectorAll(".filter").forEach((button) => button.addEventListener("click", () => {
  activeFilter = button.dataset.filter;
  selectedId = null;
  document.querySelectorAll(".filter").forEach((item) => item.classList.toggle("active", item === button));
  renderList(); renderDetail();
}));
$("#search").addEventListener("input", () => { selectedId = null; renderList(); renderDetail(); });
$("#metric-key").addEventListener("change", toggleLevelFields);
$("#pending").addEventListener("click", () => save("pending"));
$("#exclude").addEventListener("click", () => save("excluded"));
$("#confirm").addEventListener("click", () => save("confirmed"));
$("#bulk-confirm").addEventListener("click", bulkConfirm);
$("#previous").addEventListener("click", () => move(-1));
$("#next").addEventListener("click", () => move(1));
document.addEventListener("keydown", (event) => {
  if (["INPUT","TEXTAREA","SELECT"].includes(document.activeElement?.tagName)) return;
  if (event.key === "ArrowLeft") move(-1);
  if (event.key === "ArrowRight") move(1);
});

async function init() {
  $("#reviewer").value = localStorage.getItem("metric-reviewer") || "";
  try {
    state = await api("/api/state");
    selectedId = filteredMetrics()[0]?.observation_id || null;
    renderAll();
  } catch (error) {
    document.body.innerHTML = `<main class="fatal"><h1>指标工作台加载失败</h1><p>${escapeHtml(error.message)}</p></main>`;
  }
}
init();
