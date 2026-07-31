export type ReviewStatus = "needs_review" | "confirmed" | "rejected";

export type EventKind = "unclassified" | "new_feature" | "growth" | "combat" | "system";

export interface ReviewCandidate {
  id: string;
  title: string;
  eventKind: EventKind;
  status: ReviewStatus;
  timeMs: number;
  timecode: string;
  source: "click_frame" | "ocr" | "ai" | "manual_frame" | "manual_video_frame";
  confidence: number;
  ocrText: string;
  evidenceFile: string;
  evidenceUrl?: string;
  eventId: string;
  note: string;
  contactSheet?: string;
  contactSheetTileId?: string;
  sheetRow?: number;
  sheetColumn?: number;
  videoX?: number | null;
  videoY?: number | null;
  videoFile?: string;
  frameStatus?: "pending_export" | "materialized";
}

export interface ContactSheetTile {
  id: string;
  eventId: string;
  timeMs: number;
  timecode: string;
  row: number;
  column: number;
  videoX: number | null;
  videoY: number | null;
  reason: string;
}

export interface ContactSheetPage {
  name: string;
  url: string;
  rows: number;
  columns: number;
  tiles: ContactSheetTile[];
}
