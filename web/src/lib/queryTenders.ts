import type { TenderRecord } from "./tenderColumns";
import { SELECT_LIST } from "./tenderColumns";
import { getDb, rowToTenderRecord } from "./db";
import { matchesSoftwareFilter } from "./registryClassifier";

export type SoftwareFilterMode = "none" | "broad" | "strict" | "near_miss";

export type SortKey = "publication_desc" | "publication_asc";

export interface TendersQuery {
  q?: string;
  authority?: string;
  cpv?: string;
  software: SoftwareFilterMode;
  page: number;
  pageSize: number;
  sort: SortKey;
}

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

  const whereSql = parts.length ? `WHERE ${parts.join(" AND ")}` : "";
  return { sql: whereSql, params };
}

export interface TendersPageResult {
  items: TenderRecord[];
  total: number;
  page: number;
  pageSize: number;
  sort: SortKey;
}

export function queryTendersPage(query: TendersQuery): TendersPageResult {
  const db = getDb();
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
  const items: TenderRecord[] = [];
  let total = 0;
  for (const row of allRows.iterate(...whereParams) as Iterable<
    Record<string, unknown>
  >) {
    const rec = rowToTenderRecord(row);
    if (matchesSoftwareFilter(rec, query.software)) {
      total += 1;
      if (total > offset && items.length < query.pageSize) {
        items.push(rec);
      }
    }
  }

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
