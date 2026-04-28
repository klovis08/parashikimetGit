import Database from "better-sqlite3";
import { dbAvailabilityDetails } from "./db";
import { classifySoftwareScored } from "./registryClassifier";
import { getTenderById } from "./queryTenders";
import {
  parseLabelPayload,
  type AnalystLabelValue,
  type LabelPayload,
} from "./feedbackLabelsPayload";

export interface AnalystLabelRecord {
  id: number;
  tender_id: number;
  label: AnalystLabelValue;
  reviewer: string | null;
  note: string | null;
  timestamp: string;
  snapshot: {
    score: number;
    confidence: "high" | "medium" | "low";
    top_signals: string[];
    broad_ok: boolean;
    strict_ok: boolean;
    near_miss_ok: boolean;
    reasons: {
      broad: string[];
      strict_excluded: string[];
      near_miss: string[];
      mixed: string[];
    };
  };
}

export { parseLabelPayload, type LabelPayload };

function getWritableDb(): Database.Database {
  const details = dbAvailabilityDetails();
  if (!details.ok) {
    throw new Error(details.reason ?? "database unavailable");
  }
  return new Database(details.selectedPath, { fileMustExist: true, readonly: false });
}

function ensureLabelSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS analyst_labels (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tender_id INTEGER NOT NULL,
      label TEXT NOT NULL CHECK (label IN ('relevant', 'not_relevant', 'maybe')),
      reviewer TEXT,
      note TEXT,
      created_at TEXT NOT NULL,
      snapshot_score INTEGER NOT NULL,
      snapshot_confidence TEXT NOT NULL,
      snapshot_top_signals_json TEXT NOT NULL,
      snapshot_broad_ok INTEGER NOT NULL,
      snapshot_strict_ok INTEGER NOT NULL,
      snapshot_near_miss_ok INTEGER NOT NULL,
      snapshot_reasons_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_analyst_labels_tender_id_created_at
    ON analyst_labels (tender_id, created_at DESC);
  `);
}

export function createLabelForTender(
  tenderId: number,
  payload: LabelPayload,
): AnalystLabelRecord {
  const tender = getTenderById(tenderId);
  if (!tender) throw new Error("tender_not_found");
  const scored = classifySoftwareScored(tender);
  const db = getWritableDb();
  try {
    ensureLabelSchema(db);
    const createdAt = new Date().toISOString();
    const insert = db.prepare(`
      INSERT INTO analyst_labels (
        tender_id, label, reviewer, note, created_at,
        snapshot_score, snapshot_confidence, snapshot_top_signals_json,
        snapshot_broad_ok, snapshot_strict_ok, snapshot_near_miss_ok,
        snapshot_reasons_json
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    const res = insert.run(
      tenderId,
      payload.label,
      payload.reviewer,
      payload.note,
      createdAt,
      scored.score,
      scored.confidence,
      JSON.stringify(scored.topSignals),
      scored.broad.ok ? 1 : 0,
      scored.strict.ok ? 1 : 0,
      scored.nearMiss.ok ? 1 : 0,
      JSON.stringify({
        broad: scored.broad.reasons,
        strict_excluded: scored.strict.excludedReasons,
        near_miss: scored.nearMiss.reasons,
        mixed: scored.mixed.reasons,
      }),
    );
    return {
      id: Number(res.lastInsertRowid),
      tender_id: tenderId,
      label: payload.label,
      reviewer: payload.reviewer,
      note: payload.note,
      timestamp: createdAt,
      snapshot: {
        score: scored.score,
        confidence: scored.confidence,
        top_signals: scored.topSignals,
        broad_ok: scored.broad.ok,
        strict_ok: scored.strict.ok,
        near_miss_ok: scored.nearMiss.ok,
        reasons: {
          broad: scored.broad.reasons,
          strict_excluded: scored.strict.excludedReasons,
          near_miss: scored.nearMiss.reasons,
          mixed: scored.mixed.reasons,
        },
      },
    };
  } finally {
    db.close();
  }
}

export function getLabelsForTender(tenderId: number, limit = 20): AnalystLabelRecord[] {
  const db = getWritableDb();
  try {
    ensureLabelSchema(db);
    const rows = db
      .prepare(
        `
        SELECT
          id, tender_id, label, reviewer, note, created_at,
          snapshot_score, snapshot_confidence, snapshot_top_signals_json,
          snapshot_broad_ok, snapshot_strict_ok, snapshot_near_miss_ok,
          snapshot_reasons_json
        FROM analyst_labels
        WHERE tender_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
      `,
      )
      .all(tenderId, Math.max(1, limit)) as Array<Record<string, unknown>>;
    return rows.map((r) => {
      const reasonsRaw = JSON.parse(String(r.snapshot_reasons_json || "{}")) as Record<
        string,
        string[]
      >;
      return {
        id: Number(r.id),
        tender_id: Number(r.tender_id),
        label: String(r.label) as AnalystLabelValue,
        reviewer: r.reviewer ? String(r.reviewer) : null,
        note: r.note ? String(r.note) : null,
        timestamp: String(r.created_at),
        snapshot: {
          score: Number(r.snapshot_score),
          confidence: String(r.snapshot_confidence) as "high" | "medium" | "low",
          top_signals: JSON.parse(String(r.snapshot_top_signals_json || "[]")) as string[],
          broad_ok: Number(r.snapshot_broad_ok) === 1,
          strict_ok: Number(r.snapshot_strict_ok) === 1,
          near_miss_ok: Number(r.snapshot_near_miss_ok) === 1,
          reasons: {
            broad: reasonsRaw.broad ?? [],
            strict_excluded: reasonsRaw.strict_excluded ?? [],
            near_miss: reasonsRaw.near_miss ?? [],
            mixed: reasonsRaw.mixed ?? [],
          },
        },
      };
    });
  } finally {
    db.close();
  }
}
