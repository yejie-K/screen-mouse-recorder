(() => {
  const boot = () => {
    const controls = Array.from(document.querySelectorAll(".workspace-shell-session"));
    if (!controls.length) {
      window.setTimeout(boot, 50);
      return;
    }

  const browseButtons = controls.map((control) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "workspace-shell-browse";
    button.textContent = "浏览";
    button.title = "选择其他磁盘或文件夹中的Session";
    button.setAttribute("aria-label", "浏览Session文件夹");
    control.insertAdjacentElement("afterend", button);
    return button;
  });
  const shutdownButtons = controls.map((control) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "workspace-shell-shutdown";
    button.textContent = "退出分析";
    button.title = "关闭历程分析工具";
    button.setAttribute("aria-label", "关闭历程分析工具");
    control.closest(".workspace-shell-context")?.append(button);
    return button;
  });
  const preparationPanel = document.createElement("aside");
  preparationPanel.className = "workspace-shell-preparation";
  preparationPanel.hidden = true;
  preparationPanel.setAttribute("role", "status");
  preparationPanel.setAttribute("aria-live", "polite");
  preparationPanel.innerHTML = `
    <div class="workspace-shell-preparation__heading"><strong>Session准备中</strong><span>0%</span></div>
    <div class="workspace-shell-preparation__track"><i></i></div>
    <p>正在初始化分析资料</p>
  `;
  document.body.append(preparationPanel);

  let currentId = "";
  let preparationTimer = 0;

  const setDisabled = (disabled) => {
    controls.forEach((control) => {
      control.disabled = disabled;
    });
    browseButtons.forEach((button) => {
      button.disabled = disabled;
    });
  };

  const populate = (payload) => {
    currentId = String(payload.current_id || "");
    controls.forEach((control) => {
      control.replaceChildren();
      (payload.sessions || []).forEach((session) => {
        const option = document.createElement("option");
        option.value = String(session.id || "");
        option.textContent = String(session.label || session.session_id || "未命名Session");
        option.disabled = !session.prepared && !session.preparable;
        option.selected = Boolean(session.current);
        option.title = String(session.reason || "");
        option.dataset.prepared = session.prepared ? "true" : "false";
        option.dataset.preparable = session.preparable ? "true" : "false";
        control.append(option);
      });
      control.disabled = false;
      control.title = "切换整套Session数据";
    });
  };

  const waitForManualSave = async () => {
    const status = document.querySelector(".session-health");
    if (!status) return;
    const deadline = Date.now() + 2500;
    while (Date.now() < deadline && /正在保存|正在加载/.test(status.textContent || "")) {
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }
    if (/保存失败/.test(status.textContent || "")) {
      throw new Error("当前人工选帧保存失败，请先处理后再切换Session");
    }
  };

  const switchSession = async (control) => {
    const selected = control.options[control.selectedIndex];
    const workspaceId = String(control.value || "");
    if (!workspaceId || workspaceId === currentId) return;
    if (selected?.dataset.prepared !== "true") {
      control.value = currentId;
      await prepareRawSession(workspaceId, selected?.textContent || "原始Session");
      return;
    }
    const accepted = window.confirm(`切换到「${selected?.textContent || "目标Session"}」？\n未提交的表单输入不会保留。`);
    if (!accepted) {
      control.value = currentId;
      return;
    }
    setDisabled(true);
    try {
      await waitForManualSave();
      const response = await fetch("/api/workspace/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_id: workspaceId }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || `切换失败：${response.status}`);
      window.location.reload();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Session切换失败");
      control.value = currentId;
      setDisabled(false);
    }
  };

  const selectSuggestedWorkspace = async (workspaceId) => {
    await waitForManualSave();
    const response = await fetch("/api/workspace/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: workspaceId }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || `切换失败：${response.status}`);
    window.location.reload();
  };

  const showPreparation = (state) => {
    const status = String(state?.status || "idle");
    const percent = Math.max(0, Math.min(100, Number(state?.percent || 0)));
    const active = status === "running" || status === "starting";
    browseButtons.forEach((button) => {
      button.textContent = active ? `${percent}%` : "浏览";
      button.title = String(state?.message || "选择其他磁盘或文件夹中的Session");
    });
    preparationPanel.hidden = !active;
    if (active) {
      const heading = preparationPanel.querySelector(".workspace-shell-preparation__heading strong");
      const value = preparationPanel.querySelector(".workspace-shell-preparation__heading span");
      const bar = preparationPanel.querySelector(".workspace-shell-preparation__track i");
      const detail = preparationPanel.querySelector("p");
      if (heading) heading.textContent = status === "starting" ? "正在启动Session准备" : "Session准备中";
      if (value) value.textContent = `${percent}%`;
      if (bar instanceof HTMLElement) bar.style.width = `${percent}%`;
      if (detail) {
        const current = Math.max(0, Number(state?.current || 0));
        const total = Math.max(0, Number(state?.total || 0));
        const count = total > 0 ? ` · ${current}/${total}` : "";
        detail.textContent = `${String(state?.message || "正在初始化分析资料")}${count}`;
      }
    }
    return status;
  };

  const pollPreparation = async () => {
    window.clearTimeout(preparationTimer);
    try {
      const response = await fetch("/api/workspace/prepare", { cache: "no-store" });
      const state = await response.json();
      if (!response.ok) throw new Error(state.message || "准备状态读取失败");
      const status = showPreparation(state);
      if (status === "complete" && state.workspace_id) {
        await selectSuggestedWorkspace(String(state.workspace_id));
        return;
      }
      if (status === "failed") {
        setDisabled(false);
        window.alert(`Session准备失败：${state.message || "未知错误"}`);
        return;
      }
      if (status === "running" || status === "starting") {
        setDisabled(true);
        preparationTimer = window.setTimeout(pollPreparation, 800);
      } else {
        setDisabled(false);
      }
    } catch (error) {
      setDisabled(false);
      window.alert(error instanceof Error ? error.message : "Session准备状态读取失败");
    }
  };

  const prepareRawSession = async (workspaceId, label) => {
    const gameName = window.prompt(`为「${label}」填写游戏名称：`, "");
    if (gameName === null) return;
    if (!gameName.trim()) {
      window.alert("游戏名称不能为空");
      return;
    }
    setDisabled(true);
    try {
      const response = await fetch("/api/workspace/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_id: workspaceId, game_name: gameName.trim() }),
      });
      const state = await response.json();
      if (!response.ok) throw new Error(state.message || `准备失败：${response.status}`);
      showPreparation(state);
      preparationTimer = window.setTimeout(pollPreparation, 500);
    } catch (error) {
      setDisabled(false);
      window.alert(error instanceof Error ? error.message : "Session准备启动失败");
    }
  };

  const browseSession = async () => {
    setDisabled(true);
    try {
      const response = await fetch("/api/workspace/browse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || `选择失败：${response.status}`);
      if (payload.status === "cancelled") return;
      populate(payload);
      if (payload.suggested_id) {
        await selectSuggestedWorkspace(String(payload.suggested_id));
        return;
      }
      if (payload.suggested_prepare_id) {
        await prepareRawSession(String(payload.suggested_prepare_id), "原始Session");
        return;
      }
      if (payload.message) window.alert(payload.message);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Session文件夹选择失败");
    } finally {
      setDisabled(false);
    }
  };

  const shutdownWorkbench = async () => {
    if (!window.confirm("关闭历程分析工具？\n后台服务会停止，当前页面将无法继续使用。")) return;
    shutdownButtons.forEach((button) => {
      button.disabled = true;
    });
    try {
      await waitForManualSave();
      const response = await fetch("/api/shutdown", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || `关闭失败：${response.status}`);
      document.body.innerHTML = '<main class="workspace-shell-stopped"><strong>历程分析工具已关闭</strong><span>现在可以关闭此页面。</span></main>';
      window.setTimeout(() => window.close(), 300);
    } catch (error) {
      shutdownButtons.forEach((button) => {
        button.disabled = false;
      });
      window.alert(error instanceof Error ? error.message : "关闭分析工具失败");
    }
  };

  controls.forEach((control) => {
    control.disabled = true;
    control.addEventListener("change", () => switchSession(control));
  });
  browseButtons.forEach((button) => {
    button.addEventListener("click", browseSession);
  });
  shutdownButtons.forEach((button) => {
    button.addEventListener("click", shutdownWorkbench);
  });

  fetch("/api/workspaces", { cache: "no-store" })
    .then(async (response) => {
      if (!response.ok) throw new Error(`Session列表加载失败：${response.status}`);
      return response.json();
    })
    .then(populate)
    .then(pollPreparation)
    .catch((error) => {
      console.error(error);
      controls.forEach((control) => {
        control.replaceChildren(new Option("当前Session", ""));
        control.title = "统一工作台未提供Session切换";
      });
    });
  };

  boot();
})();
