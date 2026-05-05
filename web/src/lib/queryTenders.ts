import type { TenderRecord } from "./tenderColumns";
import { SELECT_LIST } from "./tenderColumns";
import { getDb, rowToTenderRecord } from "./db";
import {
  classifySoftwareScored,
  type ConfidenceTier,
  matchesSoftwareFilter,
} from "./registryClassifier";

export type SoftwareFilterMode = "none" | "broad" | "strict" | "near_miss";

export type SortKey = "publication_desc" | "publication_asc";

export interface TendersQuery {
  q?: string;
  authority?: string;
  cpv?: string;
  kohaZhvillimit?: string;
  /** Substring match against reviewer on the tender's latest analyst label */
  reviewer?: string;
  software: SoftwareFilterMode;
  page: number;
  pageSize: number;
  sort: SortKey;
  confidence?: ConfidenceTier;
}

export interface TenderSoftwareMeta {
  score: number;
  confidence: ConfidenceTier;
  topSignals: string[];
}

export type TenderListItem = TenderRecord & {
  softwareMeta?: TenderSoftwareMeta;
};

/** Escape % and _ for SQL LIKE with ESCAPE '\' */
export function escapeLikeLiteral(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_");
}

const ORDER_SQL: Record<SortKey, string> = {
  publication_desc:
    "ORDER BY data_iso DESC NULLS LAST, id DESC",
  publication_asc:
    "ORDER BY data_iso ASC NULLS FIRST, id ASC",
};

function buildWhereClause(query: TendersQuery): { sql: string; params: unknown[] } {
  const parts: string[] = [];
  const params: unknown[] = [];

  if (query.q?.trim()) {
    const lit = `%${escapeLikeLiteral(query.q.trim())}%`;
    parts.push(
      `(objekti_procedurave LIKE ? ESCAPE '\\' OR autoriteti_kontraktues LIKE ? ESCAPE '\\' OR kodi_cpv_raw LIKE ? ESCAPE '\\')`,
    );
    params.push(lit, lit, lit);
  }

  if (query.authority?.trim()) {
    const lit = `%${escapeLikeLiteral(query.authority.trim())}%`;
    parts.push(`autoriteti_kontraktues LIKE ? ESCAPE '\\'`);
    params.push(lit);
  }

  if (query.cpv?.trim()) {
    const lit = `%${escapeLikeLiteral(query.cpv.trim())}%`;
    parts.push(`kodi_cpv_raw LIKE ? ESCAPE '\\'`);
    params.push(lit);
  }

  if (query.kohaZhvillimit?.trim()) {
    const lit = `%${escapeLikeLiteral(query.kohaZhvillimit.trim())}%`;
    parts.push(`koha_zhvillimit LIKE ? ESCAPE '\\'`);
    params.push(lit);
  }

  if (query.reviewer?.trim()) {
    const lit = `%${escapeLikeLiteral(query.reviewer.trim())}%`;
    parts.push(
      `EXISTS (
        SELECT 1 FROM analyst_labels l
        WHERE l.tender_id = tenders.id
          AND l.id = (
            SELECT l2.id FROM analyst_labels l2
            WHERE l2.tender_id = tenders.id
            ORDER BY l2.created_at DESC, l2.id DESC
            LIMIT 1
          )
          AND l.reviewer LIKE ? ESCAPE '\\'
      )`,
    );
    params.push(lit);
  }

  const whereSql = parts.length ? `WHERE ${parts.join(" AND ")}` : "";
  return { sql: whereSql, params };
}

function analystLabelsTableExists(db: ReturnType<typeof getDb>): boolean {
  const row = db
    .prepare(
      `SELECT 1 AS ok FROM sqlite_master WHERE type = 'table' AND name = 'analyst_labels' LIMIT 1`,
    )
    .get() as { ok: number } | undefined;
  return row != null;
}

export interface TendersPageResult {
  items: TenderListItem[];
  total: number;
  page: number;
  pageSize: number;
  sort: SortKey;
}

function confidenceRank(confidence: ConfidenceTier): number {
  if (confidence === "high") return 3;
  if (confidence === "medium") return 2;
  return 1;
}

export function compareSoftwarePriority(
  a: TenderListItem,
  b: TenderListItem,
  sort: SortKey,
): number {
  const aMeta = a.softwareMeta;
  const bMeta = b.softwareMeta;
  const aRank = aMeta ? confidenceRank(aMeta.confidence) : 0;
  const bRank = bMeta ? confidenceRank(bMeta.confidence) : 0;
  if (bRank !== aRank) return bRank - aRank;
  const aScore = aMeta?.score ?? 0;
  const bScore = bMeta?.score ?? 0;
  if (bScore !== aScore) return bScore - aScore;
  const aDate = a.data_iso ?? "";
  const bDate = b.data_iso ?? "";
  if (aDate !== bDate) {
    return sort === "publication_asc"
      ? aDate.localeCompare(bDate)
      : bDate.localeCompare(aDate);
  }
  return sort === "publication_asc" ? a.id - b.id : b.id - a.id;
}

export function queryTendersPage(query: TendersQuery): TendersPageResult {
  const db = getDb();
  if (query.reviewer?.trim() && !analystLabelsTableExists(db)) {
    return {
      items: [],
      total: 0,
      page: query.page,
      pageSize: query.pageSize,
      sort: query.sort,
    };
  }
  const { sql: whereSql, params: whereParams } = buildWhereClause(query);
  const orderSql = ORDER_SQL[query.sort];

  if (query.software === "none") {
    const countStmt = db.prepare(
      `SELECT COUNT(*) as n FROM tenders ${whereSql}`,
    );
    const total = Number(
      (countStmt.get(...whereParams) as { n: number }).n,
    );
    const offset = (query.page - 1) * query.pageSize;
    const rows = db
      .prepare(
        `SELECT ${SELECT_LIST} FROM tenders ${whereSql} ${orderSql} LIMIT ? OFFSET ?`,
      )
      .all(...whereParams, query.pageSize, offset) as Record<
        string,
        unknown
      >[];
    return {
      items: rows.map(rowToTenderRecord),
      total,
      page: query.page,
      pageSize: query.pageSize,
      sort: query.sort,
    };
  }

  const allRows = db
    .prepare(`SELECT ${SELECT_LIST} FROM tenders ${whereSql} ${orderSql}`);

  const offset = (query.page - 1) * query.pageSize;
  const filtered: TenderListItem[] = [];
  for (const row of allRows.iterate(...whereParams) as Iterable<
    Record<string, unknown>
  >) {
    const rec = rowToTenderRecord(row);
    if (!matchesSoftwareFilter(rec, query.software)) {
      continue;
    }
    const scored = classifySoftwareScored(rec);
    if (query.confidence && scored.confidence !== query.confidence) {
      continue;
    }
    filtered.push({
      ...rec,
      softwareMeta: {
        score: scored.score,
        confidence: scored.confidence,
        topSignals: scored.topSignals,
      },
    });
  }
  filtered.sort((a, b) => compareSoftwarePriority(a, b, query.sort));
  const total = filtered.length;
  const items = filtered.slice(offset, offset + query.pageSize);

  return {
    items,
    total,
    page: query.page,
    pageSize: query.pageSize,
    sort: query.sort,
  };
}

export function getTenderById(id: number): TenderRecord | null {
  const db = getDb();
  const row = db
    .prepare(`SELECT ${SELECT_LIST} FROM tenders WHERE id = ?`)
    .get(id) as Record<string, unknown> | undefined;
  if (!row) return null;
  return rowToTenderRecord(row);
}

/** Full row for detail view (all SQLite columns). */
export function getTenderDetailById(
  id: number,
): Record<string, string | number | null> | null {
  const db = getDb();
  const row = db
    .prepare(`SELECT * FROM tenders WHERE id = ?`)
    .get(id) as Record<string, unknown> | undefined;
  if (!row) return null;
  const out: Record<string, string | number | null> = {};
  for (const [k, v] of Object.entries(row)) {
    if (v == null) out[k] = null;
    else if (typeof v === "number" || typeof v === "string") out[k] = v;
    else if (typeof v === "bigint") out[k] = Number(v);
    else out[k] = String(v);
  }
  return out;
}
