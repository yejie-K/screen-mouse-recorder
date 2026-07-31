const STATUS = { needs_review: "待复核", confirmed: "已确认", excluded: "已排除" };
const METRIC_LABELS = {
  combat_power: "战力", level: "等级", level_rebirth: "转生 + 等级",
  vip_level: "VIP等级", currency: "货币 / 资源", unknown: "暂不确定",
};
const PARSER_LABELS = {
  numeric_cn: "中文单位数值（11.04万）", integer: "整数（805）",
  level_rebirth: "转生等级（10转805级）", text: "文本（不转数字）",
};
const DEFAULT_PARSERS = {
  combat_power: "numeric_cn", level: "integer", level_rebirth: "level_rebirth",
  vip_level: "integer", currency: "numeric_cn", unknown: "text",
};
let state = null;
let selectedId = null;
let activeFilter = "needs_review";
let dragging = null;
let scanState = null;
let scanTimer = null;
const sourceSelection = new Map();
const BASE_PATH = "/regions";

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

function currentRegion() { return state?.regions.find((region) => region.region_id === selectedId) || null; }
function filteredRegions() {
  const query = $("#search").value.trim().toLowerCase();
  return (state?.regions || []).filter((region) => {
    const match = activeFilter === "all"
      || (activeFilter === "confirmed" ? region.status !== "needs_review" : region.status === activeFilter);
    const text = `${region.region_id} ${region.scene_hint} ${(region.sample_texts || []).join(" ")}`.toLowerCase();
    return match && (!query || text.includes(query));
  });
}

function renderSummary() {
  const s = state.summary;
  $("#summary").innerHTML = [[s.needs_review,"待复核"],[s.confirmed,"已确认"],[s.excluded,"已排除"]]
    .map(([value,label]) => `<div class="summary-item"><strong>${value}</strong><span>${label}</span></div>`).join("");
  const total = Number(s.needs_review || 0) + Number(s.confirmed || 0) + Number(s.excluded || 0);
  $("#calibration-progress").textContent = s.needs_review
    ? `${s.needs_review} 个区域待处理 · 共 ${total} 个`
    : `${total} 个区域已处理`;
}

function renderScan() {
  const control = $(".scan-control");
  const button = $("#start-scan");
  const progress = $("#scan-progress");
  const visible = Boolean(scanState?.available) && (
    state?.profile_status === "complete" || ["running", "complete", "error"].includes(scanState?.status)
  );
  $("#scan-panel").hidden = !visible;
  document.body.classList.toggle("scan-visible", visible);
  if (!scanState?.available) {
    control.classList.add("unavailable");
    button.disabled = true;
    $("#scan-status").textContent = "扫描未配置";
    return;
  }
  control.classList.remove("unavailable");
  const running = scanState.status === "running";
  const complete = scanState.status === "complete";
  const failed = scanState.status === "error";
  const profileReady = state?.profile_status === "complete";
  const total = Number(scanState.total || 0);
  progress.max = Math.max(1, total);
  progress.value = Math.min(total || 1, Number(scanState.done || 0));
  progress.classList.toggle("failed", failed);
  button.disabled = running || !profileReady;
  button.textContent = complete && profileReady ? "重新扫描" : "开始全量扫描";
  $("#scan-title").textContent = running ? "正在扫描" : complete && !profileReady ? "扫描结果待更新" : complete ? "扫描已完成" : failed ? "扫描失败" : "区域已就绪";
  $("#scan-next").hidden = !complete || !profileReady;
  if (running) {
    $("#scan-status").textContent = total ? `${scanState.done} / ${total}` : "准备中";
  } else if (complete && !profileReady) {
    $("#scan-status").textContent = "区域有变更，完成复核后重新扫描";
  } else if (complete) {
    $("#scan-status").textContent = `${scanState.result.frames_scanned}帧 · ${scanState.result.metric_count}条指标`;
  } else if (failed) {
    $("#scan-status").textContent = scanState.error_code || "扫描失败";
  } else {
    $("#scan-status").textContent = state?.profile_status === "complete" ? "区域已就绪" : "先完成区域复核";
  }
}

async function refreshScan() {
  try {
    scanState = await api("/api/scan-state");
    renderScan();
    if (scanState.status === "error") showMessage(scanState.error_message || "扫描失败", "error");
  } catch (error) {
    showMessage(error.message, "error");
  }
  clearTimeout(scanTimer);
  if (scanState?.status === "running") scanTimer = setTimeout(refreshScan, 800);
}

async function startScan() {
  if (!scanState?.available || state?.profile_status !== "complete") return;
  const prompt = scanState.status === "complete" ? "重新扫描会覆盖当前扫描结果，继续吗？" : "开始全部抽帧的局部OCR扫描？";
  if (!confirm(prompt)) return;
  try {
    scanState = await api("/api/scan", { method: "POST", body: "{}" });
    renderScan();
    showMessage("正式扫描已开始", "success");
    clearTimeout(scanTimer);
    scanTimer = setTimeout(refreshScan, 500);
  } catch (error) {
    showMessage(error.message, "error");
  }
}

function renderList() {
  const regions = filteredRegions();
  if (!regions.some((region) => region.region_id === selectedId)) selectedId = regions[0]?.region_id || null;
  $("#region-count").textContent = `${regions.length} 项`;
  $("#region-list").innerHTML = regions.map((region) => `<button class="region-row${region.region_id===selectedId?" selected":""}" data-id="${escapeHtml(region.region_id)}">
    <span><span class="name">${escapeHtml(region.scene_hint || region.region_id)}</span><br><small>${region.region_kind === "metric" ? "指标" : "事件"}</small></span>
    <span class="row-mark ${region.status}" title="${STATUS[region.status]}"></span>
  </button>`).join("");
  document.querySelectorAll(".region-row").forEach((row) => row.addEventListener("click", () => selectRegion(row.dataset.id)));
}

function optionHtml(values, selected, labels = {}) {
  return values.map((value) => `<option value="${escapeHtml(value)}" ${value===selected?"selected":""}>${escapeHtml(labels[value] || value)}</option>`).join("");
}

function sourceCandidates(region) {
  const all = (state?.regions || []).filter((item) => item.source_url);
  const manualById = new Map((state?.manual_samples || []).map((item) => [item.id, {
    ...item,
    manual_id: item.id,
    region_id: item.id,
    scene_hint: item.title,
    sample_evidence: [`manual:${item.id}`],
  }]));
  const manual = (region.manual_sample_ids || []).map((id) => manualById.get(id)).filter(Boolean);
  const ranked = [
    ...manual,
    region,
    ...all.filter((item) => item.region_id !== region.region_id && item.metric_key && item.metric_key === region.metric_key),
    ...all.filter((item) => item.region_id !== region.region_id && item.region_kind === region.region_kind),
    ...all,
  ];
  const seen = new Set();
  return ranked.filter((item) => {
    const key = item.sample_evidence?.[0] || item.source_url;
    if (!item.source_url || seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 3);
}

function evidenceTime(region, fallback) {
  if (region.timecode) return region.timecode.replace(/^00:/, "").replace(/\.\d+$/, "");
  const value = region.sample_evidence?.[0] || "";
  const match = value.match(/_(\d{6,})\.[^.]+$/);
  if (!match) return `样本 ${fallback + 1}`;
  const totalSeconds = Math.floor(Number(match[1]) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function renderSources(region) {
  const candidates = sourceCandidates(region);
  const selected = Math.min(sourceSelection.get(region.region_id) || 0, Math.max(0, candidates.length - 1));
  sourceSelection.set(region.region_id, selected);
  const source = candidates[selected];
  $("#source-image").src = source ? `${BASE_PATH}${source.source_url}?t=${Date.now()}` : "";
  $("#source-wrap").hidden = !source;
  $("#source-empty").hidden = Boolean(source);
  $("#source-picker").hidden = candidates.length === 0;
  $("#source-picker").innerHTML = candidates.map((item, index) => `<div class="source-choice${index === selected ? " selected" : ""}">
    <button type="button" class="source-select" data-index="${index}" title="${escapeHtml(item.scene_hint || item.region_id)}">
      <img src="${BASE_PATH}${item.source_url}" alt="代表帧 ${index + 1}"><span>${evidenceTime(item, index)}</span>
    </button>
    ${item.manual_id ? `<button type="button" class="source-remove" data-manual-id="${escapeHtml(item.manual_id)}" title="从当前区域移除" aria-label="从当前区域移除">×</button>` : ""}
  </div>`).join("");
  document.querySelectorAll(".source-select").forEach((button) => button.addEventListener("click", () => {
    sourceSelection.set(region.region_id, Number(button.dataset.index));
    renderSources(region);
    renderBoxes();
  }));
  document.querySelectorAll(".source-remove").forEach((button) => button.addEventListener("click", () => {
    region.manual_sample_ids = (region.manual_sample_ids || []).filter((id) => id !== button.dataset.manualId);
    sourceSelection.set(region.region_id, 0);
    renderSources(region);
    renderBoxes();
    $("#suggestion-result").textContent = "";
    showMessage("已从当前区域移除，点击暂存或确认保存", "success");
  }));
  const manualSamples = state?.manual_samples || [];
  $("#source-library").disabled = manualSamples.length === 0;
  $("#source-library").innerHTML = `<option value="">${manualSamples.length ? "从人工帧库选择…" : "人工帧库暂无内容"}</option>
    <option value="__auto__">恢复自动样本</option>` + manualSamples.map((item) =>
      `<option value="${escapeHtml(item.id)}">${escapeHtml(`${item.timecode || "--:--"} · ${item.title}`)}</option>`
    ).join("");
}

function sampleResultStatus(text, metricKey) {
  const value = String(text || "").trim();
  if (!value) return { label: "未识别", className: "empty" };
  if (metricKey === "combat_power") {
    if (/[\/／]/.test(value)) return { label: "疑似血量", className: "warning" };
    if (!/[战戰诚誠成]力/.test(value)) return { label: "需检查", className: "warning" };
  }
  if (metricKey === "level" && !/级/.test(value)) return { label: "需检查", className: "warning" };
  if (metricKey === "level_rebirth" && !/转|未转生/.test(value)) return { label: "需检查", className: "warning" };
  return { label: "通过", className: "" };
}

function renderSampleResults(region) {
  const texts = (region.sample_texts || []).slice(0, 3);
  const rows = texts.length ? texts : [""];
  $("#sample-texts").innerHTML = rows.map((text, index) => {
    const status = sampleResultStatus(text, region.metric_key);
    return `<div class="sample-result ${status.className}"><span>样本 ${index + 1}</span><span title="${escapeHtml(text)}">${escapeHtml(text || "无结果")}</span><em>${status.label}</em></div>`;
  }).join("");
}

function renderDetail() {
  const region = currentRegion();
  if (!region) { $("#region-name").textContent = "当前筛选没有区域"; return; }
  $("#region-name").textContent = region.scene_hint || "未命名区域";
  $("#region-kicker").textContent = `${region.region_kind === "metric" ? "数值指标" : "功能事件"} · ${region.region_id}`;
  $("#region-status").textContent = STATUS[region.status];
  $("#region-status").className = `status-badge ${region.status}`;
  $("#blockers").textContent = state.completion_blockers.join("；");
  ["left","top","right","bottom"].forEach((name,index) => { $(`#rect-${name}`).value = region.rect_normalized[index]; });
  renderSources(region);
  $("#preview-image").src = region.preview_url ? `${BASE_PATH}${region.preview_url}?t=${Date.now()}` : "";
  $("#preview-image").hidden = !region.preview_url;
  renderSampleResults(region);
  $("#region-kind").value = region.region_kind;
  $("#enabled").checked = region.enabled !== false;
  $("#scene-hint").value = region.scene_hint || "";
  $("#metric-key").innerHTML = optionHtml(state.options.metric_keys, region.metric_key, METRIC_LABELS);
  $("#parser").innerHTML = optionHtml(state.options.metric_parsers, region.parser, PARSER_LABELS);
  $("#region-role").innerHTML = optionHtml(state.options.region_roles, region.region_role);
  $("#mode-tag").innerHTML = optionHtml(state.options.mode_tags, region.mode_tag);
  $("#event-tag").innerHTML = optionHtml(state.options.event_tags, region.event_tag);
  $("#region-group").value = region.region_group_id || "";
  $("#fixed-keywords").value = (region.fixed_keywords || []).join("\n");
  toggleKind();
  renderBoxes();
  const list = filteredRegions();
  const index = list.findIndex((item) => item.region_id === selectedId);
  $("#position").textContent = `${index + 1} / ${list.length}`;
  $("#previous").disabled = index <= 0;
  $("#next").disabled = index < 0 || index >= list.length - 1;
  showMessage("");
}

function rectValues() { return ["left","top","right","bottom"].map((name) => Number($(`#rect-${name}`).value)); }
function renderBoxes() {
  const region = currentRegion();
  if (!region) { $("#region-overlay").innerHTML = ""; return; }
  const values = rectValues();
  const [left, top, right, bottom] = values.every(Number.isFinite) ? values : region.rect_normalized;
  const title = `${region.scene_hint || region.region_id} · ${STATUS[region.status]}`;
  $("#region-overlay").innerHTML = `<button type="button" class="region-box selected"
    data-id="${escapeHtml(region.region_id)}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"
    style="left:${left*100}%;top:${top*100}%;width:${(right-left)*100}%;height:${(bottom-top)*100}%">
    ${["n","ne","e","se","s","sw","w","nw"].map((handle) => `<span class="resize-handle" data-handle="${handle}" aria-hidden="true"></span>`).join("")}
  </button>`;
}
function updateBox() {
  const [left,top,right,bottom] = rectValues();
  const box = document.querySelector(".region-box.selected");
  if (!box) return;
  box.style.left = `${left*100}%`; box.style.top = `${top*100}%`;
  box.style.width = `${(right-left)*100}%`; box.style.height = `${(bottom-top)*100}%`;
}
function toggleKind() {
  const metric = $("#region-kind").value === "metric";
  document.querySelectorAll(".kind-toggle button").forEach((button) => button.classList.toggle("active", button.dataset.kind === $("#region-kind").value));
  $("#metric-fields").hidden = !metric;
  $("#metric-suggestion").hidden = !metric;
  $("#event-fields").hidden = metric;
  $("#parser-field").hidden = !metric;
  $("#event-advanced").hidden = metric;
}
function selectRegion(id) { selectedId = id; renderList(); renderDetail(); }
function move(delta) { const list=filteredRegions(); const i=list.findIndex((r)=>r.region_id===selectedId); if(list[i+delta]) selectRegion(list[i+delta].region_id); }
function showMessage(text, kind="") { $("#message").textContent=text; $("#message").className=`message ${kind}`; }

async function addMetricRegion() {
  try {
    const result = await api("/api/region/new", {
      method: "POST",
      body: JSON.stringify({ sample_region_id: selectedId }),
    });
    state = result.state;
    selectedId = result.region_id;
    activeFilter = "needs_review";
    document.querySelectorAll(".filter").forEach((item) => item.classList.toggle("active", item.dataset.filter === activeFilter));
    renderAll();
    showMessage("已新增待复核区域，请选择画面、调整框和识别内容", "success");
  } catch (error) { showMessage(error.message, "error"); }
}

function chooseManualSource() {
  const region = currentRegion();
  const value = $("#source-library").value;
  if (!region || !value) return;
  if (value === "__auto__") {
    region.manual_sample_ids = [];
  } else {
    region.manual_sample_ids = [value, ...(region.manual_sample_ids || []).filter((id) => id !== value)].slice(0, 3);
  }
  sourceSelection.set(region.region_id, 0);
  renderSources(region);
  renderBoxes();
  $("#suggestion-result").textContent = "";
}

async function suggestMetric() {
  const region = currentRegion();
  if (!region || $("#region-kind").value !== "metric") return;
  const button = $("#suggest-metric");
  button.disabled = true;
  $("#suggestion-result").textContent = "正在识别选区…";
  try {
    const result = await api("/api/suggest-metric", {
      method: "POST",
      body: JSON.stringify({
        region_id: region.region_id,
        rect_normalized: rectValues(),
        manual_sample_ids: region.manual_sample_ids || [],
      }),
    });
    $("#metric-key").value = result.metric_key;
    $("#parser").value = result.parser;
    const texts = (result.ocr_texts || []).filter(Boolean);
    region.sample_texts = texts.slice(0, 8);
    region.metric_key = result.metric_key;
    renderSampleResults(region);
    $("#suggestion-result").textContent = `${result.reason} · ${Math.round((result.confidence || 0) * 100)}%`;
  } catch (error) {
    $("#suggestion-result").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function save(decision) {
  const region = currentRegion(); if (!region) return;
  const reviewer = $("#reviewer").value.trim();
  if (["confirmed","excluded"].includes(decision) && !reviewer) { showMessage("请填写复核人", "error"); return; }
  const rect = rectValues();
  if (rect.some((value) => !Number.isFinite(value)) || !(rect[0] < rect[2] && rect[1] < rect[3])) { showMessage("区域坐标无效", "error"); return; }
  const payload = {
    region_id: region.region_id, decision, reviewer, enabled: $("#enabled").checked,
    region_kind: $("#region-kind").value, rect_normalized: rect, scene_hint: $("#scene-hint").value,
    manual_sample_ids: region.manual_sample_ids || [],
    sample_texts: region.sample_texts || [],
    metric_key: $("#metric-key").value, parser: $("#parser").value,
    region_group_id: $("#region-group").value, region_role: $("#region-role").value,
    fixed_keywords: $("#fixed-keywords").value.split(/\r?\n/).map((v)=>v.trim()).filter(Boolean),
    mode_tag: $("#mode-tag").value, event_tag: $("#event-tag").value,
  };
  try {
    state = await api("/api/region", { method:"POST", body:JSON.stringify(payload) });
    localStorage.setItem("region-reviewer", reviewer);
    if (decision === "confirmed") {
      activeFilter = "needs_review";
      selectedId = state.regions.find((item) => item.status === "needs_review")?.region_id || region.region_id;
      document.querySelectorAll(".filter").forEach((item) => item.classList.toggle("active", item.dataset.filter === activeFilter));
    }
    renderAll(); showMessage(decision === "confirmed" ? "区域已确认" : `已保存为${STATUS[decision]}`, "success");
  } catch (error) { showMessage(error.message, "error"); }
}

function renderAll() {
  $("#title").textContent = state.game.game_name;
  $("#profile-status").textContent = state.profile_status === "complete" ? "区域配置已完成" : "区域配置待复核";
  renderSummary(); renderList(); renderDetail(); renderScan();
}

function renderOCRStatus() {
  const ocr = state?.ocr || { available: false, message: "OCR状态未知" };
  const button = $("#suggest-metric");
  button.disabled = !ocr.available;
  button.title = ocr.message || "";
  $("#suggestion-result").textContent = ocr.available ? "" : ocr.message;
}

document.querySelectorAll(".filter").forEach((button) => button.addEventListener("click", () => {
  activeFilter=button.dataset.filter; selectedId=null;
  document.querySelectorAll(".filter").forEach((item)=>item.classList.toggle("active",item===button)); renderList(); renderDetail();
}));
$("#search").addEventListener("input",()=>{selectedId=null;renderList();renderDetail();});
$("#region-kind").addEventListener("change",toggleKind);
document.querySelectorAll(".kind-toggle button").forEach((button) => button.addEventListener("click", () => {
  $("#region-kind").value = button.dataset.kind;
  toggleKind();
}));
$("#metric-key").addEventListener("change",()=>{$("#parser").value=DEFAULT_PARSERS[$("#metric-key").value]||"text";});
$("#source-library").addEventListener("change",chooseManualSource);
$("#suggest-metric").addEventListener("click",suggestMetric);
["left","top","right","bottom"].forEach((name)=>$("#rect-"+name).addEventListener("input",updateBox));
$("#add-metric").addEventListener("click",addMetricRegion);
$("#pending").addEventListener("click",()=>save("needs_review"));
$("#exclude").addEventListener("click",()=>save("excluded"));
$("#confirm").addEventListener("click",()=>save("confirmed"));
$("#previous").addEventListener("click",()=>move(-1));
$("#next").addEventListener("click",()=>move(1));
$("#start-scan").addEventListener("click", startScan);
$("#region-overlay").addEventListener("pointerdown",(event)=>{
  const box=event.target.closest(".region-box");
  if(!box)return;
  if(box.dataset.id!==selectedId){selectRegion(box.dataset.id);return;}
  const wrap=$("#source-wrap").getBoundingClientRect();
  const handle=event.target.closest(".resize-handle")?.dataset.handle || "move";
  dragging={mode:handle,x:event.clientX,y:event.clientY,rect:rectValues(),width:wrap.width,height:wrap.height};
  box.setPointerCapture(event.pointerId);
});
$("#region-overlay").addEventListener("pointermove",(event)=>{
  if(!dragging)return;
  const dx=(event.clientX-dragging.x)/dragging.width,dy=(event.clientY-dragging.y)/dragging.height;
  let [l,t,r,b]=dragging.rect;
  const minX=Math.max(.008,8/dragging.width),minY=Math.max(.008,8/dragging.height);
  if(dragging.mode==="move"){
    const w=r-l,h=b-t;
    l=Math.max(0,Math.min(1-w,l+dx)); t=Math.max(0,Math.min(1-h,t+dy)); r=l+w; b=t+h;
  }else{
    if(dragging.mode.includes("w")) l=Math.max(0,Math.min(r-minX,l+dx));
    if(dragging.mode.includes("e")) r=Math.min(1,Math.max(l+minX,r+dx));
    if(dragging.mode.includes("n")) t=Math.max(0,Math.min(b-minY,t+dy));
    if(dragging.mode.includes("s")) b=Math.min(1,Math.max(t+minY,b+dy));
  }
  [["left",l],["top",t],["right",r],["bottom",b]].forEach(([n,v])=>$("#rect-"+n).value=v.toFixed(6));
  updateBox();
});
$("#region-overlay").addEventListener("pointerup",()=>{dragging=null;});
$("#region-overlay").addEventListener("pointercancel",()=>{dragging=null;});

async function init() {
  $("#reviewer").value=localStorage.getItem("region-reviewer")||"";
  try {
    [state, scanState] = await Promise.all([api("/api/state"), api("/api/scan-state")]);
    if (state.summary.needs_review === 0 && state.summary.confirmed > 0) {
      activeFilter = "confirmed";
      document.querySelectorAll(".filter").forEach((item) => item.classList.toggle("active", item.dataset.filter === activeFilter));
    }
    selectedId=filteredRegions()[0]?.region_id||null;
    renderAll();
    renderOCRStatus();
    if (scanState.status === "running") scanTimer = setTimeout(refreshScan, 500);
  }
  catch(error){document.body.innerHTML=`<main class="fatal"><h1>区域工作台加载失败</h1><p>${escapeHtml(error.message)}</p></main>`;}
}
init();
