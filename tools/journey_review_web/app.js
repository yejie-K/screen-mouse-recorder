const STATUS_LABELS = { pending: "待复核", confirmed: "已确认", excluded: "已排除" };
let state = null;
let selectedId = null;
let activeFilter = "flagged";
const BASE_PATH = "/events";

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
})[char]);

async function api(path, options = {}) {
  const response = await fetch(`${BASE_PATH}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message || "请求失败");
  return payload;
}

function currentEvent() {
  return state?.events.find((event) => event.event_id === selectedId) || null;
}

function filteredEvents() {
  if (!state) return [];
  const query = $("#search").value.trim().toLowerCase();
  return state.events.filter((event) => {
    const status = event.decision.decision;
    const filterMatch = activeFilter === "all"
      || (activeFilter === "flagged" && event.review_items.length > 0 && status === "pending")
      || status === activeFilter;
    const haystack = `${event.event_name} ${event.ocr_excerpt} ${event.event_type} ${event.mode_tag} ${event.event_tag}`.toLowerCase();
    return filterMatch && (!query || haystack.includes(query));
  });
}

function renderSummary() {
  const summary = state.summary;
  const items = [
    [summary.pending, "待复核"],
    [summary.confirmed, "已确认"],
    [summary.excluded, "已排除"],
    [summary.metric_observations, "指标样本"],
  ];
  $("#summary").innerHTML = items.map(([value, label]) =>
    `<div class="summary-item"><strong>${value}</strong><span>${label}</span></div>`
  ).join("");
}

function renderList() {
  const events = filteredEvents();
  $("#event-count").textContent = `${events.length} 个OCR候选`;
  $("#event-list").innerHTML = events.map((event) => {
    const selected = event.event_id === selectedId ? " selected" : "";
    const flag = event.review_items.length ? `<span class="flag">需核对</span>` : "";
    return `<button class="event-row${selected}" data-event-id="${escapeHtml(event.event_id)}">
      <span class="time">${escapeHtml(event.timestamp).slice(3, 8)}</span>
      <span class="name">${escapeHtml(event.event_name)} ${flag}</span>
      <span class="row-mark ${event.decision.decision}" title="${STATUS_LABELS[event.decision.decision]}"></span>
    </button>`;
  }).join("");
  document.querySelectorAll(".event-row").forEach((row) => {
    row.addEventListener("click", () => selectEvent(row.dataset.eventId));
  });
  if (!events.some((event) => event.event_id === selectedId)) {
    selectedId = events[0]?.event_id || null;
  }
}

function renderTagGroup(target, name, tags, selected) {
  $(target).innerHTML = tags.map((tag) => `
    <label class="tag-option">
      <input type="radio" name="${name}" value="${escapeHtml(tag)}" ${selected === tag ? "checked" : ""}>
      <span>${escapeHtml(tag)}</span>
    </label>`).join("");
}

function selectedValue(name) {
  return document.querySelector(`input[name="${name}"]:checked`)?.value || "";
}

function renderProfile(event) {
  const target = $("#profile-match");
  if (!event.profile_match) {
    target.innerHTML = "";
    return;
  }
  const mapping = event.profile_match.mapping;
  const modeTag = mapping.mode_tag || "待判断";
  const eventTag = mapping.event_tag || "其他开放";
  target.innerHTML = `<div class="profile-banner">
    <strong>已命中本游戏词典：${escapeHtml(event.profile_match.term)}</strong>
    <div>${escapeHtml(modeTag)} · ${escapeHtml(eventTag)}</div>
    <button id="apply-profile" class="button secondary">应用词典映射</button>
  </div>`;
  $("#apply-profile").addEventListener("click", () => applyTags(modeTag, eventTag));
}

function applyTags(modeTag, eventTag) {
  renderTagGroup("#mode-options", "mode-tag", state.mode_tags, modeTag);
  renderTagGroup("#event-options", "event-tag", state.event_tags, eventTag);
  showMessage("已应用本游戏标签，保存后生效", "success");
}

function renderDetail() {
  const event = currentEvent();
  if (!event) {
    $("#event-name").textContent = "暂无OCR功能事件候选";
    $("#event-kicker").textContent = "人工选帧已在上一步确认，不进入本页重复复核";
    $("#event-status").textContent = "";
    $("#mode-options").innerHTML = "";
    $("#event-options").innerHTML = "";
    $("#evidence-image").removeAttribute("src");
    $("#evidence-image").hidden = true;
    $("#evidence-empty").textContent = "当前没有需要复核的OCR证据";
    $("#evidence-empty").hidden = false;
    $("#ocr-text").textContent = "";
    $("#review-alerts").innerHTML = "";
    return;
  }
  $("#event-name").textContent = event.event_name;
  $("#event-kicker").textContent = `${event.timestamp} · ${event.event_type} · 置信度 ${Math.round(event.candidate.confidence * 100)}%`;
  $("#event-status").textContent = STATUS_LABELS[event.decision.decision];
  $("#event-status").className = `status-badge ${event.decision.decision}`;
  $("#review-alerts").innerHTML = event.review_items.map((item) =>
    `<div class="alert"><strong>${escapeHtml(item.reason)}</strong>${escapeHtml(item.suggested_action)}</div>`
  ).join("");
  const image = $("#evidence-image");
  const empty = $("#evidence-empty");
  if (event.evidence_url) {
    image.src = `${BASE_PATH}${event.evidence_url}?t=${Date.now()}`;
    image.hidden = false;
    empty.hidden = true;
  } else {
    image.removeAttribute("src");
    image.hidden = true;
    empty.hidden = false;
  }
  $("#ocr-text").textContent = event.ocr_excerpt || "";
  renderTagGroup("#mode-options", "mode-tag", state.mode_tags, event.mode_tag);
  renderTagGroup("#event-options", "event-tag", state.event_tags, event.event_tag);
  $("#review-note").value = event.decision.review_note || "";
  $("#save-profile").checked = Boolean(event.decision.save_to_game_profile);
  $("#game-term").value = event.decision.game_term || event.event_name;
  renderProfile(event);
  const list = filteredEvents();
  const index = list.findIndex((item) => item.event_id === selectedId);
  $("#position").textContent = index >= 0 ? `${index + 1} / ${list.length}` : "0 / 0";
  $("#previous").disabled = index <= 0;
  $("#next").disabled = index < 0 || index >= list.length - 1;
  showMessage("");
}

function collectOverrides(event) {
  const modeTag = selectedValue("mode-tag");
  const eventTag = selectedValue("event-tag");
  return {
    ...(event.decision.overrides || {}),
    mode_tag: modeTag,
    event_tag: eventTag,
    tags: [modeTag, eventTag],
  };
}

function showMessage(text, kind = "") {
  const target = $("#message");
  target.textContent = text;
  target.className = `message ${kind}`;
}

async function saveDecision(decision) {
  const event = currentEvent();
  if (!event) return;
  const reviewer = $("#reviewer").value.trim();
  if (["confirmed", "excluded"].includes(decision) && !reviewer) {
    showMessage("请先填写复核人", "error");
    $("#reviewer").focus();
    return;
  }
  if (decision === "confirmed" && (!selectedValue("mode-tag") || !selectedValue("event-tag"))) {
    showMessage("请确认玩法模式和开放内容", "error");
    return;
  }
  showMessage("保存中…");
  try {
    state = await api("/api/decision", {
      method: "POST",
      body: JSON.stringify({
        event_id: event.event_id,
        decision,
        reviewer,
        overrides: collectOverrides(event),
        review_note: $("#review-note").value,
        save_to_game_profile: $("#save-profile").checked,
        game_term: $("#game-term").value,
      }),
    });
    localStorage.setItem("journey-reviewer", reviewer);
    renderAll();
    showMessage(`已保存为${STATUS_LABELS[decision]}`, "success");
    if (decision !== "pending") moveNext();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

function selectEvent(eventId) {
  selectedId = eventId;
  renderList();
  renderDetail();
}

function move(delta) {
  const list = filteredEvents();
  const index = list.findIndex((event) => event.event_id === selectedId);
  const target = list[index + delta];
  if (target) selectEvent(target.event_id);
}
function moveNext() { move(1); }

async function bulkConfirm() {
  const reviewer = $("#reviewer").value.trim();
  if (!reviewer) {
    showMessage("请先填写复核人", "error");
    return;
  }
  const eventIds = filteredEvents().filter((event) => event.decision.decision === "pending").map((event) => event.event_id);
  if (!eventIds.length) return;
  if (!confirm(`确认当前筛选中的 ${eventIds.length} 个待复核事件？`)) return;
  try {
    state = await api("/api/bulk-confirm", { method: "POST", body: JSON.stringify({ event_ids: eventIds, reviewer }) });
    renderAll();
    showMessage(`已批量确认 ${eventIds.length} 个事件`, "success");
  } catch (error) {
    showMessage(error.message, "error");
  }
}

function renderAll() {
  $("#game-title").textContent = `${state.game.game_name} · 功能事件复核`;
  $("#session-label").textContent = `事件线 · Session ${state.session.session_id}`;
  renderSummary();
  renderList();
  renderDetail();
}

async function init() {
  $("#reviewer").value = localStorage.getItem("journey-reviewer") || "";
  try {
    state = await api("/api/state");
    if (!filteredEvents().length) {
      activeFilter = state.summary.pending ? "pending" : "all";
      document.querySelectorAll(".filter").forEach((item) => {
        item.classList.toggle("active", item.dataset.filter === activeFilter);
      });
    }
    selectedId = filteredEvents()[0]?.event_id || state.events[0]?.event_id || null;
    renderAll();
  } catch (error) {
    document.body.innerHTML = `<main class="fatal"><h1>复核工作台加载失败</h1><p>${escapeHtml(error.message)}</p></main>`;
  }
}

document.querySelectorAll(".filter").forEach((button) => {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    document.querySelectorAll(".filter").forEach((item) => item.classList.toggle("active", item === button));
    selectedId = null;
    renderList();
    renderDetail();
  });
});
$("#search").addEventListener("input", () => { selectedId = null; renderList(); renderDetail(); });
$("#confirm").addEventListener("click", () => saveDecision("confirmed"));
$("#exclude").addEventListener("click", () => saveDecision("excluded"));
$("#mark-pending").addEventListener("click", () => saveDecision("pending"));
$("#previous").addEventListener("click", () => move(-1));
$("#next").addEventListener("click", () => move(1));
$("#bulk-confirm").addEventListener("click", bulkConfirm);
document.addEventListener("keydown", (event) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (event.key === "ArrowLeft") move(-1);
  if (event.key === "ArrowRight") move(1);
  if (event.ctrlKey && event.key === "Enter") saveDecision("confirmed");
});
init();
