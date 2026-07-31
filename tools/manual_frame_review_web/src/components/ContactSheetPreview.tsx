import { ChevronLeft, ChevronRight, LayoutGrid } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ContactSheetPage, ContactSheetTile } from "../domain/reviewTypes";

interface ContactSheetPreviewProps {
  pages: ContactSheetPage[];
  selectedTileId?: string;
  onSelectTile: (tile: ContactSheetTile, page: ContactSheetPage) => void;
  onQuickAddTile: (tile: ContactSheetTile, page: ContactSheetPage) => void;
}

const reasonLabels: Record<string, string> = {
  single: "独立点击",
  cluster_start: "重复点击起点",
  cluster_end: "重复点击终点",
  cluster_edge: "重复点击边界",
  visual_change: "点击后画面变化",
};

export function ContactSheetPreview({ pages, selectedTileId, onSelectTile, onQuickAddTile }: ContactSheetPreviewProps) {
  const [pageIndex, setPageIndex] = useState(0);
  const [hoveredTile, setHoveredTile] = useState<ContactSheetTile | null>(null);
  const [pendingFocusTileId, setPendingFocusTileId] = useState<string | null>(null);
  const [isKeyboardActive, setIsKeyboardActive] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const tileButtonRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    setPageIndex(0);
    setHoveredTile(null);
    setIsKeyboardActive(false);
  }, [pages]);

  useEffect(() => {
    if (!pendingFocusTileId) return;
    const button = tileButtonRefs.current.get(pendingFocusTileId);
    if (!button) return;
    button.focus();
    setPendingFocusTileId(null);
  }, [pageIndex, pendingFocusTileId]);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!panelRef.current?.contains(event.target as Node)) setIsKeyboardActive(false);
    };
    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => document.removeEventListener("pointerdown", handlePointerDown, true);
  }, []);

  const page = pages[pageIndex];
  const selectRelativeTile = useCallback((offset: -1 | 1) => {
    if (!page) return;
    const orderedTiles = [...page.tiles].sort((left, right) => left.row - right.row || left.column - right.column);
    const currentIndex = orderedTiles.findIndex((tile) => tile.id === selectedTileId);
    if (currentIndex < 0) return;

    const nextIndex = currentIndex + offset;
    if (nextIndex >= 0 && nextIndex < orderedTiles.length) {
      const nextTile = orderedTiles[nextIndex];
      setHoveredTile(nextTile);
      onSelectTile(nextTile, page);
      tileButtonRefs.current.get(nextTile.id)?.focus();
      return;
    }

    const nextPageIndex = pageIndex + offset;
    const nextPage = pages[nextPageIndex];
    if (!nextPage) return;
    const nextPageTiles = [...nextPage.tiles].sort((left, right) => left.row - right.row || left.column - right.column);
    const nextTile = offset > 0 ? nextPageTiles[0] : nextPageTiles[nextPageTiles.length - 1];
    if (!nextTile) return;
    setPageIndex(nextPageIndex);
    setHoveredTile(nextTile);
    setPendingFocusTileId(nextTile.id);
    onSelectTile(nextTile, nextPage);
  }, [onSelectTile, page, pageIndex, pages, selectedTileId]);

  useEffect(() => {
    if (!isKeyboardActive || !page) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, [contenteditable='true']")) return;
      if (event.code === "Space" || event.key === " " || event.key === "Spacebar") {
        const tile = page.tiles.find((candidate) => candidate.id === selectedTileId);
        if (!tile) return;
        event.preventDefault();
        onQuickAddTile(tile, page);
        return;
      }
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      selectRelativeTile(event.key === "ArrowLeft" ? -1 : 1);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isKeyboardActive, onQuickAddTile, page, selectRelativeTile, selectedTileId]);

  const magnifierStyle = useMemo(() => {
    if (!page || !hoveredTile) return undefined;
    const x = page.columns <= 1 ? 0 : ((hoveredTile.column - 1) / (page.columns - 1)) * 100;
    const y = page.rows <= 1 ? 0 : ((hoveredTile.row - 1) / (page.rows - 1)) * 100;
    return {
      backgroundImage: `url(${page.url})`,
      backgroundSize: `${page.columns * 100}% ${page.rows * 100}%`,
      backgroundPosition: `${x}% ${y}%`,
    };
  }, [hoveredTile, page]);

  if (!page) return null;

  return (
    <aside ref={panelRef} className="contact-sheet-panel">
      <div className="contact-sheet-header">
        <div>
          <LayoutGrid size={15} />
          <span>抽帧拼图</span>
        </div>
      </div>

      <div className="contact-sheet-canvas">
        <img src={page.url} alt={`抽帧拼图 ${pageIndex + 1}`} />
        <div
          className="contact-sheet-grid"
          style={{ gridTemplateColumns: `repeat(${page.columns}, 1fr)`, gridTemplateRows: `repeat(${page.rows}, 1fr)` }}
        >
          {page.tiles.map((tile) => (
            <button
              key={tile.id}
              ref={(element) => {
                if (element) tileButtonRefs.current.set(tile.id, element);
                else tileButtonRefs.current.delete(tile.id);
              }}
              type="button"
              className={`contact-sheet-tile ${selectedTileId === tile.id ? "is-selected" : ""}`}
              style={{ gridColumn: tile.column, gridRow: tile.row }}
              title={`${tile.timecode} ${tile.eventId} · 方向键切换，空格添加`}
              aria-keyshortcuts="ArrowLeft ArrowRight Space"
              onMouseEnter={() => setHoveredTile(tile)}
              onMouseLeave={() => setHoveredTile(null)}
              onFocus={() => setHoveredTile(tile)}
              onBlur={() => setHoveredTile(null)}
              onClick={() => {
                setIsKeyboardActive(true);
                onSelectTile(tile, page);
              }}
            />
          ))}
        </div>
      </div>

      <div className="contact-sheet-footer">
        <div className="contact-sheet-pager">
          <button
            className="contact-sheet-page-button"
            type="button"
            title="上一页拼图"
            disabled={pageIndex === 0}
            onClick={() => {
              setIsKeyboardActive(false);
              setPageIndex((value) => Math.max(0, value - 1));
              setHoveredTile(null);
            }}
          >
            <ChevronLeft size={14} />
          </button>
          <span>{pageIndex + 1} / {pages.length}</span>
          <button
            className="contact-sheet-page-button"
            type="button"
            title="下一页拼图"
            disabled={pageIndex >= pages.length - 1}
            onClick={() => {
              setIsKeyboardActive(false);
              setPageIndex((value) => Math.min(pages.length - 1, value + 1));
              setHoveredTile(null);
            }}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {hoveredTile && (
        <div className="contact-sheet-popover">
          <div className="contact-sheet-magnifier" style={magnifierStyle} />
          <div className="contact-sheet-detail">
            <strong>{hoveredTile.timecode}</strong>
            <span>{hoveredTile.eventId}</span>
            <span>{reasonLabels[hoveredTile.reason] ?? hoveredTile.reason}</span>
            <span>
              坐标 {hoveredTile.videoX ?? "-"}, {hoveredTile.videoY ?? "-"}
            </span>
          </div>
        </div>
      )}
    </aside>
  );
}
