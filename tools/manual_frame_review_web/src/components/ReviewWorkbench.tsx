import {
  Check,
  CheckCircle2,
  Camera,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  Clock3,
  Columns2,
  Database,
  Download,
  FolderOpen,
  ImageIcon,
  Maximize2,
  MousePointerClick,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Save,
  ScanText,
  Search,
  SlidersHorizontal,
  X,
  ZoomIn,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import type { ContactSheetPage, ContactSheetTile, EventKind, ReviewCandidate, ReviewStatus } from "../domain/reviewTypes";
import { ContactSheetPreview } from "./ContactSheetPreview";

export type ProductView = "review" | "confirmed";

interface ReviewWorkbenchProps {
  activeView: ProductView;
  onViewChange: (view: ProductView) => void;
}

const statusLabels: Record<ReviewStatus, string> = {
  needs_review: "待复核",
  confirmed: "已确认",
  rejected: "已排除",
};

const WORKSPACE_BASE = "/manual";
const workspaceUrl = (value?: string) => value?.startsWith("/") ? `${WORKSPACE_BASE}${value}` : value;

const kindLabels: Record<EventKind, string> = {
  unclassified: "待分类",
  new_feature: "功能开放",
  growth: "成长变化",
  combat: "战斗事件",
  system: "系统引导",
};

const sourceLabels: Record<ReviewCandidate["source"], string> = {
  click_frame: "点击帧",
  ocr: "OCR",
  ai: "AI 候选",
  manual_frame: "人工选帧",
  manual_video_frame: "人工视频补帧",
};

const DEFAULT_CONTACT_SHEET_WIDTH = 230;
const MIN_CONTACT_SHEET_WIDTH = 180;
const MAX_CONTACT_SHEET_WIDTH = 380;
const MIN_EVIDENCE_WIDTH = 300;
const MANUAL_CANDIDATE_STORAGE_PREFIX = "journey-review-manual-candidates-v3";

function isScaffoldCandidate(candidate: ReviewCandidate) {
  return candidate.id.startsWith("real_candidate_")
    && candidate.source === "click_frame"
    && candidate.confidence === 1
    && candidate.ocrText === "尚未执行 OCR";
}

function isManualCandidate(candidate: ReviewCandidate) {
  return candidate.source === "manual_frame" || candidate.source === "manual_video_frame";
}

function loadManualCandidates(sessionId: string) {
  try {
    const raw = window.localStorage.getItem(`${MANUAL_CANDIDATE_STORAGE_PREFIX}:${sessionId}`);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ReviewCandidate[];
    return Array.isArray(parsed) ? parsed.filter(isManualCandidate) : [];
  } catch {
    return [];
  }
}

function mergeCandidates(runtimeCandidates: ReviewCandidate[], manualCandidates: ReviewCandidate[]) {
  const merged = new Map(runtimeCandidates.map((candidate) => [candidate.id, candidate]));
  manualCandidates.forEach((candidate) => merged.set(candidate.id, candidate));
  return [...merged.values()].sort((left, right) => left.timeMs - right.timeMs);
}

function nextPendingCandidate(candidates: ReviewCandidate[], currentId: string) {
  const currentIndex = candidates.findIndex((candidate) => candidate.id === currentId);
  const ordered = [...candidates.slice(currentIndex + 1), ...candidates.slice(0, currentIndex + 1)];
  return ordered.find((candidate) => candidate.status === "needs_review")?.id ?? currentId;
}

function formatTimecode(ms: number) {
  const totalMs = Math.max(0, Math.round(ms));
  const hours = Math.floor(totalMs / 3_600_000);
  const minutes = Math.floor((totalMs % 3_600_000) / 60_000);
  const seconds = Math.floor((totalMs % 60_000) / 1000);
  const millis = totalMs % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

function downloadEvents(candidates: ReviewCandidate[], filename: string, schemaVersion: string) {
  const payload = {
    schemaVersion,
    exportedAt: new Date().toISOString(),
    events: candidates,
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ReviewWorkbench({ activeView, onViewChange }: ReviewWorkbenchProps) {
  const [candidates, setCandidates] = useState<ReviewCandidate[]>([]);
  const [baselineCandidates, setBaselineCandidates] = useState<ReviewCandidate[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("轻量 MMO · 首次体验");
  const [storageSessionId, setStorageSessionId] = useState<string | null>(null);
  const [durationMs, setDurationMs] = useState(1_800_000);
  const [durationTimecode, setDurationTimecode] = useState("00:30:00.000");
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoFile, setVideoFile] = useState("recording.mp4");
  const [contactSheets, setContactSheets] = useState<ContactSheetPage[]>([]);
  const [filter, setFilter] = useState<"pending" | "all">("pending");
  const [query, setQuery] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);
  const [isZoomed, setIsZoomed] = useState(false);
  const [playbackMs, setPlaybackMs] = useState(0);
  const [previewTile, setPreviewTile] = useState<ContactSheetTile | null>(null);
  const [previewPage, setPreviewPage] = useState<ContactSheetPage | null>(null);
  const [isCreatingEvent, setIsCreatingEvent] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftKind, setDraftKind] = useState<EventKind>("unclassified");
  const [draftNote, setDraftNote] = useState("");
  const [contactSheetWidth, setContactSheetWidth] = useState(DEFAULT_CONTACT_SHEET_WIDTH);
  const [persistenceStatus, setPersistenceStatus] = useState<"loading" | "saved" | "saving" | "error">("loading");
  const videoRef = useRef<HTMLVideoElement>(null);
  const evidenceVisualsRef = useRef<HTMLDivElement>(null);
  const stateLoadedRef = useRef(false);
  const saveTimerRef = useRef<number | null>(null);

  useEffect(() => {
    fetch(`${WORKSPACE_BASE}/api/state`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`加载人工选帧状态失败：${response.status}`);
        return (await response.json()) as {
          projectName?: string;
          sessionId?: string;
          durationMs?: number;
          durationTimecode?: string;
          videoUrl?: string;
          videoFile?: string;
          contactSheets?: ContactSheetPage[];
          candidates?: ReviewCandidate[];
          manualCandidates?: ReviewCandidate[];
        };
      })
      .then((runtime) => {
        const sessionId = runtime.sessionId ?? runtime.projectName ?? "local-session";
        const runtimeCandidates = (runtime.candidates ?? []).filter((candidate) => !isScaffoldCandidate(candidate));
        const persistedCandidates = runtime.manualCandidates?.length
          ? runtime.manualCandidates
          : loadManualCandidates(sessionId);
        const initialCandidates = mergeCandidates(runtimeCandidates, persistedCandidates);
        setStorageSessionId(sessionId);
        setCandidates(initialCandidates);
        setBaselineCandidates(initialCandidates);
        setSelectedId(initialCandidates[0]?.id ?? null);
        setPlaybackMs(initialCandidates[0]?.timeMs ?? 0);
        if (runtime.projectName) setProjectName(runtime.projectName);
        if (runtime.durationMs) setDurationMs(runtime.durationMs);
        if (runtime.durationTimecode) setDurationTimecode(runtime.durationTimecode);
        if (runtime.videoUrl) {
          setVideoUrl(workspaceUrl(runtime.videoUrl) ?? null);
          const videoUrlParts = runtime.videoUrl.split("/").filter(Boolean);
          const inferredVideoFile = videoUrlParts[videoUrlParts.length - 1];
          setVideoFile(runtime.videoFile ?? inferredVideoFile ?? "recording.mp4");
        } else if (runtime.videoFile) {
          setVideoFile(runtime.videoFile);
        }
        if (runtime.contactSheets) {
          setContactSheets(runtime.contactSheets.map((page) => ({
            ...page,
            url: workspaceUrl(page.url) ?? page.url,
          })));
        }
        stateLoadedRef.current = true;
        setPersistenceStatus("saved");
      })
      .catch((error) => {
        console.error(error);
        setCandidates([]);
        setBaselineCandidates([]);
        setPersistenceStatus("error");
      });
  }, []);

  useEffect(() => {
    if (!stateLoadedRef.current || !storageSessionId) return;
    const manualCandidates = candidates.filter(isManualCandidate);
    setPersistenceStatus("saving");
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => {
      fetch(`${WORKSPACE_BASE}/api/manual-selections`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: storageSessionId, candidates: manualCandidates }),
      })
        .then((response) => {
          if (!response.ok) throw new Error(`保存人工选帧失败：${response.status}`);
          window.localStorage.removeItem(`${MANUAL_CANDIDATE_STORAGE_PREFIX}:${storageSessionId}`);
          setPersistenceStatus("saved");
        })
        .catch((error) => {
          console.error(error);
          setPersistenceStatus("error");
        });
    }, 350);
    return () => {
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    };
  }, [candidates, storageSessionId]);

  const selected = selectedId ? candidates.find((candidate) => candidate.id === selectedId) ?? null : null;
  const pendingCount = candidates.filter((candidate) => candidate.status === "needs_review").length;
  const confirmed = candidates.filter((candidate) => candidate.status === "confirmed");
  const selectedIndex = selected ? candidates.findIndex((candidate) => candidate.id === selected.id) : -1;

  useEffect(() => {
    if (!selected || previewTile) return;
    setPlaybackMs(selected.timeMs);
    setIsPlaying(false);
    setIsZoomed(false);
    const video = videoRef.current;
    if (!video || !videoUrl) return;
    video.pause();
    if (video.readyState >= 1) video.currentTime = selected.timeMs / 1000;
  }, [previewTile, selected, videoUrl]);

  useEffect(() => {
    const saved = Number(window.localStorage.getItem("journey-review-contact-width"));
    if (Number.isFinite(saved) && saved >= MIN_CONTACT_SHEET_WIDTH && saved <= MAX_CONTACT_SHEET_WIDTH) {
      setContactSheetWidth(saved);
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem("journey-review-contact-width", String(Math.round(contactSheetWidth)));
  }, [contactSheetWidth]);

  const visibleCandidates = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return candidates.filter((candidate) => {
      if (filter === "pending" && candidate.status !== "needs_review") return false;
      if (!normalizedQuery) return true;
      return `${candidate.title} ${candidate.timecode} ${candidate.ocrText}`.toLocaleLowerCase().includes(normalizedQuery);
    });
  }, [candidates, filter, query]);

  const updateCandidate = (id: string, patch: Partial<ReviewCandidate>) => {
    setCandidates((current) =>
      current.map((candidate) => (candidate.id === id ? { ...candidate, ...patch } : candidate)),
    );
  };

  const seekVideoToMs = useCallback((targetMs: number) => {
    const nextMs = Math.max(0, Math.min(durationMs, targetMs));
    setPlaybackMs(nextMs);
    const video = videoRef.current;
    if (!video) return;
    video.pause();
    if (video.readyState >= 1) video.currentTime = nextMs / 1000;
  }, [durationMs]);

  const handleTimelineSeek = (targetMs: number) => {
    setPreviewTile(null);
    setPreviewPage(null);
    setIsCreatingEvent(false);
    seekVideoToMs(targetMs);
  };

  const selectCandidate = (candidateId: string) => {
    setPreviewTile(null);
    setPreviewPage(null);
    setIsCreatingEvent(false);
    setSelectedId(candidateId);
  };

  const setDecision = (status: Extract<ReviewStatus, "confirmed" | "rejected">) => {
    if (!selected) return;
    if (status === "confirmed" && selected.eventKind === "unclassified") return;
    updateCandidate(selected.id, { status });
    selectCandidate(nextPendingCandidate(candidates, selected.id));
  };

  const selectRelativeCandidate = (offset: number) => {
    if (!selected) return;
    const nextIndex = selectedIndex + offset;
    if (nextIndex < 0 || nextIndex >= candidates.length) return;
    selectCandidate(candidates[nextIndex].id);
  };

  const handleContactTileSelect = (tile: ContactSheetTile, page: ContactSheetPage) => {
    const matchingCandidate = candidates.find((candidate) => candidate.eventId === tile.eventId);
    setSelectedId(matchingCandidate?.id ?? null);
    setPreviewTile(tile);
    setPreviewPage(page);
    setIsCreatingEvent(false);
    seekVideoToMs(tile.timeMs);
  };

  const beginCreateEvent = () => {
    if (!previewTile || !previewPage) return;
    setDraftTitle("");
    setDraftKind("unclassified");
    setDraftNote("");
    setIsCreatingEvent(true);
  };

  const cancelCreateEvent = () => {
    setIsCreatingEvent(false);
    setDraftTitle("");
    setDraftNote("");
  };

  const appendManualCandidate = (
    tile: ContactSheetTile,
    page: ContactSheetPage,
    title: string,
    eventKind: EventKind,
    note: string,
  ) => {
    const existing = candidates.find((candidate) => candidate.eventId === tile.eventId);
    if (existing) {
      setSelectedId(existing.id);
      return;
    }
    const candidate: ReviewCandidate = {
      id: `manual_${tile.eventId}_${Date.now().toString(36)}`,
      title,
      eventKind,
      status: "needs_review",
      timeMs: tile.timeMs,
      timecode: tile.timecode,
      source: "manual_frame",
      confidence: 1,
      ocrText: "尚未执行 OCR",
      evidenceFile: `${page.name} · ${tile.id}`,
      eventId: tile.eventId,
      note,
      contactSheet: page.name,
      contactSheetTileId: tile.id,
      sheetRow: tile.row,
      sheetColumn: tile.column,
      videoX: tile.videoX,
      videoY: tile.videoY,
    };
    setCandidates((current) => [...current, candidate].sort((left, right) => left.timeMs - right.timeMs));
    setBaselineCandidates((current) => [...current, candidate].sort((left, right) => left.timeMs - right.timeMs));
    setSelectedId(candidate.id);
  };

  const quickAddManualEvent = (tile: ContactSheetTile, page: ContactSheetPage) => {
    appendManualCandidate(
      tile,
      page,
      `待标注事件 · ${tile.timecode}`,
      "unclassified",
      "空格快捷添加，待补充事件名称与类型。",
    );
    setIsCreatingEvent(false);
  };

  const quickAddCurrentVideoFrame = () => {
    const video = videoRef.current;
    if (!video || !videoUrl) return;
    video.pause();
    const timeMs = Math.max(0, Math.round(video.currentTime * 1000));
    setPlaybackMs(timeMs);
    const existing = candidates.find(
      (candidate) => candidate.source === "manual_video_frame" && Math.abs(candidate.timeMs - timeMs) <= 100,
    );
    if (existing) {
      setPreviewTile(null);
      setPreviewPage(null);
      setIsCreatingEvent(false);
      setSelectedId(existing.id);
      return;
    }

    const timecode = formatTimecode(timeMs);
    const fileTimecode = timecode.replace(/:/g, "-").replace(".", "-");
    const candidate: ReviewCandidate = {
      id: `manual_video_${timeMs}_${Date.now().toString(36)}`,
      title: `待标注视频帧 · ${timecode}`,
      eventKind: "unclassified",
      status: "needs_review",
      timeMs,
      timecode,
      source: "manual_video_frame",
      confidence: 1,
      ocrText: "尚未执行 OCR",
      evidenceFile: `manual_frames/manual_frame_${fileTimecode}.jpg`,
      eventId: `manual_video_${timeMs}`,
      note: "人工从视频当前画面补帧，等待批量导出原始帧。",
      videoFile,
      frameStatus: "pending_export",
    };
    setCandidates((current) => [...current, candidate].sort((left, right) => left.timeMs - right.timeMs));
    setBaselineCandidates((current) => [...current, candidate].sort((left, right) => left.timeMs - right.timeMs));
    setPreviewTile(null);
    setPreviewPage(null);
    setIsCreatingEvent(false);
    setSelectedId(candidate.id);
  };

  const saveManualEvent = () => {
    if (!previewTile || !previewPage || !draftTitle.trim()) return;
    appendManualCandidate(previewTile, previewPage, draftTitle.trim(), draftKind, draftNote.trim());
    setPreviewTile(null);
    setPreviewPage(null);
    setIsCreatingEvent(false);
    setDraftTitle("");
    setDraftNote("");
  };

  const handleSplitterPointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const container = evidenceVisualsRef.current;
    if (!container) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = contactSheetWidth;
    const containerWidth = container.getBoundingClientRect().width;
    const maxWidth = Math.max(
      MIN_CONTACT_SHEET_WIDTH,
      Math.min(MAX_CONTACT_SHEET_WIDTH, containerWidth - MIN_EVIDENCE_WIDTH - 8),
    );

    const handlePointerMove = (moveEvent: PointerEvent) => {
      const nextWidth = startWidth - (moveEvent.clientX - startX);
      setContactSheetWidth(Math.max(MIN_CONTACT_SHEET_WIDTH, Math.min(maxWidth, nextWidth)));
    };
    const handlePointerUp = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
  };

  const togglePlayback = async () => {
    const video = videoRef.current;
    if (!videoUrl || !video) return;
    if (video.paused) {
      try {
        await video.play();
      } catch {
        setIsPlaying(false);
      }
    } else {
      video.pause();
    }
  };

  const restoreSelectedCandidate = () => {
    if (!selected) return;
    const baseline = baselineCandidates.find((candidate) => candidate.id === selected.id);
    if (baseline) updateCandidate(selected.id, baseline);
  };

  return (
    <div className="product-shell workspace-shell-root">
      <header className="product-topbar workspace-shell-header">
        <div className="product-brand workspace-shell-brand">
          <span className="product-brand__mark workspace-shell-brand__mark">历</span>
          <div className="workspace-shell-brand__copy">
            <strong>历程拆解</strong>
            <span>Journey Review</span>
          </div>
        </div>
        <nav className="product-nav workspace-shell-nav" aria-label="产品视图">
          <button type="button" className="active" onClick={() => onViewChange("review")}>
            人工选帧
          </button>
          <a href="/regions/">区域校准</a>
          <a href="/events/">功能事件</a>
          <a href="/metrics/">指标结果</a>
        </nav>
        <div className="workspace-shell-context">
          <div className="workspace-shell-page">
            <strong>人工选帧工作台</strong>
            <select className="workspace-shell-session" aria-label="切换Session" defaultValue="">
              <option value="">{projectName}</option>
            </select>
          </div>
          <div className={`session-health ${persistenceStatus === "error" ? "has-error" : ""}`} title="人工选帧保存状态">
            <CheckCircle2 size={16} />
            {persistenceStatus === "loading" && "正在加载"}
            {persistenceStatus === "saving" && "正在保存"}
            {persistenceStatus === "saved" && "已保存"}
            {persistenceStatus === "error" && "保存失败"}
          </div>
        </div>
      </header>

      <div className="manual-toolbar workspace-shell-toolbar">
        <strong className="manual-toolbar__title">
          {activeView === "confirmed" ? "已确认事件" : "人工选帧"}
        </strong>
        {activeView === "review" ? (
          <>
            <div className="manual-filter-group" role="tablist" aria-label="候选筛选">
              <button className={filter === "pending" ? "active" : ""} onClick={() => setFilter("pending")}>
                待复核
              </button>
              <button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>
                全部
              </button>
            </div>
            <label className="manual-search">
              <Search size={15} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索事件或时间" />
            </label>
          </>
        ) : (
          <button className="manual-toolbar__back" type="button" onClick={() => onViewChange("review")}>
            返回人工选帧
          </button>
        )}
        <div className="workspace-shell-summary" aria-label="人工复核进度">
          <div className="summary-item"><strong>{pendingCount}</strong><span>待复核</span></div>
          <div className="summary-item"><strong>{confirmed.length}</strong><span>已确认</span></div>
        </div>
      </div>

      {activeView === "confirmed" ? (
        <ConfirmedEventsView candidates={confirmed} onBack={() => onViewChange("review")} />
      ) : (
        <main className="review-workspace workspace-shell-main">
          <aside className="candidate-panel">
            <div className="section-heading">
              <div>
                <span>候选事件</span>
                <strong>{pendingCount}</strong>
              </div>
              <div className="section-heading__actions">
                <button
                  className="icon-button"
                  type="button"
                  title="查看已确认事件"
                  onClick={() => onViewChange("confirmed")}
                >
                  <Database size={16} />
                </button>
                <button
                  className="icon-button"
                  type="button"
                  title="导出候选事件"
                  disabled={candidates.length === 0}
                  onClick={() => downloadEvents(candidates, "review_candidates.json", "review-candidates-0.1")}
                >
                  <Download size={16} />
                </button>
                <button className="icon-button" type="button" title="筛选条件">
                  <SlidersHorizontal size={16} />
                </button>
              </div>
            </div>
            <div className="candidate-list">
              {visibleCandidates.map((candidate) => (
                <button
                  key={candidate.id}
                  type="button"
                  className={`candidate-row ${selected?.id === candidate.id ? "active" : ""}`}
                  onClick={() => selectCandidate(candidate.id)}
                >
                  <span className={`candidate-row__status status-${candidate.status}`} />
                  <span className="candidate-row__content">
                    <strong>{candidate.title}</strong>
                    <span>
                      <Clock3 size={12} />
                      {candidate.timecode}
                      <em>{sourceLabels[candidate.source]}</em>
                    </span>
                  </span>
                  <ChevronRight size={15} />
                </button>
              ))}
              {visibleCandidates.length === 0 && <div className="candidate-empty">暂无候选事件，请从拼图选择有效帧</div>}
            </div>
          </aside>

          <section className="evidence-workspace">
            <div className="evidence-toolbar">
              <div>
                <span className="evidence-title">证据画面</span>
                <span className="evidence-counter">{selected ? `${selectedIndex + 1} / ${candidates.length}` : `0 / ${candidates.length}`}</span>
              </div>
              <div className="evidence-tools">
                <button className="icon-button" type="button" title="上一帧" disabled={!selected || selectedIndex <= 0} onClick={() => selectRelativeCandidate(-1)}>
                  <ChevronLeft size={17} />
                </button>
                <button className="icon-button" type="button" title="下一帧" disabled={!selected || selectedIndex >= candidates.length - 1} onClick={() => selectRelativeCandidate(1)}>
                  <ChevronRight size={17} />
                </button>
                <button className="icon-button" type="button" title="放大画面" aria-pressed={isZoomed} onClick={() => setIsZoomed(true)}>
                  <ZoomIn size={17} />
                </button>
                <button className="icon-button" type="button" title="适应窗口" onClick={() => setIsZoomed(false)}>
                  <Maximize2 size={17} />
                </button>
                <button
                  className="icon-button"
                  type="button"
                  title="将当前视频帧加入待复核"
                  disabled={!videoUrl}
                  onClick={quickAddCurrentVideoFrame}
                >
                  <Camera size={17} />
                </button>
                <button className="icon-button" type="button" title="恢复默认画面比例" onClick={() => setContactSheetWidth(DEFAULT_CONTACT_SHEET_WIDTH)}>
                  <Columns2 size={17} />
                </button>
                <button className="icon-button" type="button" title="打开证据文件" disabled={!selected?.evidenceUrl} onClick={() => selected?.evidenceUrl && window.open(selected.evidenceUrl, "_blank", "noopener,noreferrer")}>
                  <FolderOpen size={17} />
                </button>
              </div>
            </div>

            <div
              ref={evidenceVisualsRef}
              className="evidence-visuals"
              style={{ "--contact-sheet-width": `${contactSheetWidth}px` } as CSSProperties}
            >
              <div className={`evidence-stage ${isZoomed ? "is-zoomed" : ""}`}>
                {videoUrl ? (
                  <video
                    ref={videoRef}
                    src={videoUrl}
                    poster={selected?.evidenceUrl}
                    preload="metadata"
                    muted
                    playsInline
                    onLoadedMetadata={(event) => {
                      event.currentTarget.currentTime = playbackMs / 1000;
                    }}
                    onPlay={() => setIsPlaying(true)}
                    onPause={() => setIsPlaying(false)}
                    onTimeUpdate={(event) => setPlaybackMs(event.currentTarget.currentTime * 1000)}
                  />
                ) : selected?.evidenceUrl ? (
                  <img src={selected.evidenceUrl} alt="当前候选事件的证据画面" />
                ) : (
                  <div className="evidence-empty-state">
                    <ImageIcon size={22} />
                    <span>从右侧拼图选择一帧</span>
                  </div>
                )}
                {!videoUrl && selected && !selected.evidenceUrl && (
                  <>
                    <div className="ocr-box ocr-box--feature">新功能开启 · 仙术</div>
                    <div className="ocr-box ocr-box--power">战力 11.04万</div>
                  </>
                )}
                <div className="frame-stamp">
                  <ImageIcon size={14} />
                  {previewTile ? `${previewTile.eventId} · 拼图定位` : selected?.evidenceFile ?? "尚未选择帧"}
                </div>
              </div>
              <button
                className="evidence-splitter"
                type="button"
                role="separator"
                aria-label="调整主画面与拼图宽度"
                aria-orientation="vertical"
                aria-valuemin={MIN_CONTACT_SHEET_WIDTH}
                aria-valuemax={MAX_CONTACT_SHEET_WIDTH}
                aria-valuenow={Math.round(contactSheetWidth)}
                title="拖动调整主画面与拼图宽度，双击恢复默认"
                onPointerDown={handleSplitterPointerDown}
                onDoubleClick={() => setContactSheetWidth(DEFAULT_CONTACT_SHEET_WIDTH)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowLeft") {
                    event.preventDefault();
                    setContactSheetWidth((value) => Math.min(MAX_CONTACT_SHEET_WIDTH, value + 10));
                  }
                  if (event.key === "ArrowRight") {
                    event.preventDefault();
                    setContactSheetWidth((value) => Math.max(MIN_CONTACT_SHEET_WIDTH, value - 10));
                  }
                  if (event.key === "Home") {
                    event.preventDefault();
                    setContactSheetWidth(DEFAULT_CONTACT_SHEET_WIDTH);
                  }
                }}
              />
              <ContactSheetPreview
                pages={contactSheets}
                selectedTileId={previewTile?.id}
                onSelectTile={handleContactTileSelect}
                onQuickAddTile={quickAddManualEvent}
              />
            </div>

            <div className="evidence-metadata">
              <span><Clock3 size={14} />{formatTimecode(playbackMs)}</span>
              <span><MousePointerClick size={14} />{previewTile?.eventId ?? selected?.eventId ?? "未选择事件"}</span>
              <span><ScanText size={14} />{previewTile ? "拼图定位预览" : selected?.ocrText ?? "选择有效帧后添加事件"}</span>
            </div>

            <div className="timeline-shell">
              <div className="timeline-controls">
                <button className="icon-button" type="button" title={isPlaying ? "暂停" : "播放"} disabled={!videoUrl} onClick={togglePlayback}>
                  {isPlaying ? <Pause size={17} /> : <Play size={17} />}
                </button>
                <strong>{formatTimecode(playbackMs)}</strong>
                <span>/ {durationTimecode}</span>
              </div>
              <div className="timeline-track" aria-label="证据时间轴">
                <span className="timeline-range" style={{ width: `${Math.max(0, Math.min(100, (playbackMs / durationMs) * 100))}%` }} />
                <input
                  className="timeline-seek"
                  type="range"
                  min={0}
                  max={Math.max(1, durationMs)}
                  step={50}
                  value={Math.max(0, Math.min(durationMs, playbackMs))}
                  aria-label="视频进度"
                  onPointerDown={() => videoRef.current?.pause()}
                  onChange={(event) => handleTimelineSeek(Number(event.target.value))}
                />
                {candidates.map((candidate) => (
                  <button
                    key={candidate.id}
                    type="button"
                    className={`timeline-marker status-${candidate.status} ${candidate.id === selected?.id ? "active" : ""}`}
                    style={{ left: `${Math.max(2, Math.min(98, (candidate.timeMs / durationMs) * 100))}%` }}
                    onClick={() => selectCandidate(candidate.id)}
                    title={`${candidate.timecode} ${candidate.title}`}
                  />
                ))}
              </div>
            </div>
          </section>

          <aside className="review-inspector">
            {isCreatingEvent && previewTile && previewPage ? (
              <>
                <div className="section-heading inspector-title">
                  <div>
                    <span>新建候选事件</span>
                    <small>{previewTile.eventId}</small>
                  </div>
                  <span className="review-status status-needs_review">待复核</span>
                </div>
                <div className="inspector-form">
                  <label>
                    <span>事件名称</span>
                    <input
                      autoFocus
                      value={draftTitle}
                      onChange={(event) => setDraftTitle(event.target.value)}
                      placeholder="例如：仙术功能开启"
                    />
                  </label>
                  <div className="form-row">
                    <label>
                      <span>事件类型</span>
                      <select value={draftKind} onChange={(event) => setDraftKind(event.target.value as EventKind)}>
                        {Object.entries(kindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </label>
                    <label>
                      <span>视频时间</span>
                      <input value={previewTile.timecode} readOnly />
                    </label>
                  </div>
                  <div className="inspector-section-block">
                    <div className="block-heading">
                      <span>证据来源</span>
                      <strong>已对齐</strong>
                    </div>
                    <div className="ocr-result">
                      <ImageIcon size={16} />
                      <span>{previewPage.name} · 第 {previewTile.row} 行第 {previewTile.column} 列</span>
                    </div>
                    <div className="source-tags">
                      <span>人工选帧</span>
                      <span>{previewTile.eventId}</span>
                      <span>时间已对齐</span>
                    </div>
                  </div>
                  <label>
                    <span>复核备注</span>
                    <textarea value={draftNote} onChange={(event) => setDraftNote(event.target.value)} placeholder="可选" />
                  </label>
                </div>
                <div className="review-actions is-create">
                  <button className="secondary-command" type="button" onClick={cancelCreateEvent}>
                    <X size={16} />
                    取消
                  </button>
                  <button className="confirm-command" type="button" disabled={!draftTitle.trim()} onClick={saveManualEvent}>
                    <Save size={16} />
                    保存候选
                  </button>
                </div>
              </>
            ) : previewTile && !selected ? (
              <>
                <div className="section-heading inspector-title">
                  <div>
                    <span>帧预览</span>
                    <small>{previewTile.eventId}</small>
                  </div>
                  <span className="review-status">未添加</span>
                </div>
                <div className="frame-preview-details">
                  <div><span>视频时间</span><strong>{previewTile.timecode}</strong></div>
                  <div><span>点击坐标</span><strong>{previewTile.videoX ?? "-"}, {previewTile.videoY ?? "-"}</strong></div>
                  <div><span>拼图位置</span><strong>第 {previewTile.row} 行第 {previewTile.column} 列</strong></div>
                  <p>确认这帧具有分析意义后，再添加为候选事件。</p>
                </div>
                <div className="review-actions is-single">
                  <button className="confirm-command" type="button" onClick={beginCreateEvent}>
                    <Plus size={17} />
                    添加事件
                  </button>
                </div>
              </>
            ) : selected ? (
              <>
                <div className="section-heading inspector-title">
                  <div>
                    <span>事件复核</span>
                    <small>{selected.id}</small>
                  </div>
                  <span className={`review-status status-${selected.status}`}>{statusLabels[selected.status]}</span>
                </div>
                <div className="inspector-form">
                  <label>
                    <span>事件名称</span>
                    <input value={selected.title} onChange={(event) => updateCandidate(selected.id, { title: event.target.value })} />
                  </label>
                  <div className="form-row">
                    <label>
                      <span>事件类型</span>
                      <select value={selected.eventKind} onChange={(event) => updateCandidate(selected.id, { eventKind: event.target.value as EventKind })}>
                        {Object.entries(kindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </label>
                    <label>
                      <span>视频时间</span>
                      <input value={selected.timecode} readOnly />
                    </label>
                  </div>
                  <div className="inspector-section-block">
                    <div className="block-heading">
                      <span>{selected.ocrText === "尚未执行 OCR" ? "抽帧来源" : "识别结果"}</span>
                      <strong>{selected.ocrText === "尚未执行 OCR" ? "已对齐" : `${Math.round(selected.confidence * 100)}%`}</strong>
                    </div>
                    <div className="ocr-result">
                      <ScanText size={16} />
                      <span>{selected.ocrText}</span>
                    </div>
                    <div className="source-tags">
                      <span>{sourceLabels[selected.source]}</span>
                      <span>{selected.source === "manual_video_frame" ? selected.videoFile ?? "recording.mp4" : "原始单帧"}</span>
                      <span>{selected.frameStatus === "pending_export" ? "待批量抽帧" : "时间已对齐"}</span>
                    </div>
                  </div>
                  <label>
                    <span>复核备注</span>
                    <textarea value={selected.note} onChange={(event) => updateCandidate(selected.id, { note: event.target.value })} />
                  </label>
                </div>
                <div className="review-actions">
                  <button className="secondary-command" type="button" onClick={restoreSelectedCandidate}>
                    <RotateCcw size={16} />
                    恢复
                  </button>
                  <button className="reject-command" type="button" onClick={() => setDecision("rejected")}>
                    <X size={17} />
                    排除
                  </button>
                  <button
                    className="confirm-command"
                    type="button"
                    disabled={selected.eventKind === "unclassified"}
                    title={selected.eventKind === "unclassified" ? "请先选择事件类型" : "确认事件"}
                    onClick={() => setDecision("confirmed")}
                  >
                    <Check size={17} />
                    确认事件
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="section-heading inspector-title">
                  <div><span>事件复核</span></div>
                </div>
                <div className="inspector-empty-state">
                  <MousePointerClick size={22} />
                  <strong>尚未选择事件</strong>
                  <span>从右侧拼图选择有意义的帧，再添加候选事件。</span>
                </div>
              </>
            )}
          </aside>
        </main>
      )}
    </div>
  );
}

function ConfirmedEventsView({ candidates, onBack }: { candidates: ReviewCandidate[]; onBack: () => void }) {
  const coverage = candidates.length ? candidates.reduce((latest, candidate) => candidate.timeMs > latest.timeMs ? candidate : latest).timecode : "00:00:00.000";
  const evidenceComplete = candidates.length > 0 && candidates.every((candidate) => Boolean(candidate.evidenceFile));

  return (
    <main className="confirmed-view workspace-shell-confirmed">
      <div className="confirmed-heading">
        <div>
          <button className="icon-button" type="button" title="返回复核工作台" onClick={onBack}>
            <ChevronLeft size={17} />
          </button>
          <div>
            <span>正式数据</span>
            <h1>已确认事件</h1>
          </div>
        </div>
        <button className="primary-command" type="button" disabled={candidates.length === 0} onClick={() => downloadEvents(candidates, "confirmed_journey_events.json", "review-events-0.1")}>
          <Download size={16} />
          导出数据
        </button>
      </div>
      <div className="confirmed-summary">
        <div><CircleDot size={17} /><span>已确认</span><strong>{candidates.length}</strong></div>
        <div><Clock3 size={17} /><span>覆盖至</span><strong>{coverage}</strong></div>
        <div><CheckCircle2 size={17} /><span>证据完整</span><strong>{evidenceComplete ? "100%" : "0%"}</strong></div>
      </div>
      <div className="confirmed-table-wrap">
        <table className="confirmed-table">
          <thead>
            <tr><th>时间</th><th>事件</th><th>类型</th><th>来源</th><th>证据</th><th>状态</th></tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => (
              <tr key={candidate.id}>
                <td>{candidate.timecode}</td>
                <td><strong>{candidate.title}</strong><small>{candidate.id}</small></td>
                <td>{kindLabels[candidate.eventKind]}</td>
                <td>{sourceLabels[candidate.source]}</td>
                <td>{candidate.evidenceFile}</td>
                <td><span className="table-status"><CheckCircle2 size={14} />已确认</span></td>
              </tr>
            ))}
            {candidates.length === 0 && (
              <tr>
                <td colSpan={6} className="confirmed-empty">暂无已确认事件</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </main>
  );
}
