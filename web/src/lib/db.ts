import fs from "fs";
import path from "path";
import Database from "better-sqlite3";
import type { TenderRecord } from "./tenderColumns";
import { TENDER_COLUMNS } from "./tenderColumns";

let _db: Database.Database | null = null;

export interface DbAvailabilityDetails {
  ok: boolean;
  selectedPath: string;
  checkedPaths: string[];
  reason?: string;
}

function resolveDbPathCandidates(): string[] {
  const fromEnv = process.env.REGISTRY_DB_PATH?.trim();
  if (fromEnv) {
    const p = path.isAbsolute(fromEnv)
      ? fromEnv
      : path.resolve(process.cwd(), fromEnv);
    return [p];
  }
  return [
    path.resolve(process.cwd(), "..", "registry.db"),
    path.resolve(process.cwd(), "registry.db"),
  ];
}

export function dbAvailabilityDetails(): DbAvailabilityDetails {
  const candidates = resolveDbPathCandidates();
  for (const p of candidates) {
    try {
      fs.accessSync(p, fs.constants.R_OK);
      return {
        ok: true,
        selectedPath: p,
        checkedPaths: candidates,
      };
    } catch {
      // try next path
    }
  }
  return {
    ok: false,
    selectedPath: candidates[0] ?? "",
    checkedPaths: candidates,
    reason: "No readable SQLite DB found. Set REGISTRY_DB_PATH to an absolute path.",
  };
}

export function getRegistryDbPath(): string {
  return dbAvailabilityDetails().selectedPath;
}

export function dbAvailable(): boolean {
  return dbAvailabilityDetails().ok;
}

export function getDb(): Database.Database {
  if (_db) return _db;
  const details = dbAvailabilityDetails();
  if (!details.ok) {
    throw new Error(
      `${details.reason} Checked: ${details.checkedPaths.join(", ")}`,
    );
  }
  const dbPath = details.selectedPath;
  _db = new Database(dbPath, { readonly: true, fileMustExist: true });
  _db.pragma("foreign_keys = ON");
  return _db;
}

/** For tests / hot reload */
export function closeDb(): void {
  if (_db) {
    _db.close();
    _db = null;
  }
}

export function rowToTenderRecord(row: Record<string, unknown>): TenderRecord {
  const id = Number(row.id);
  const out = { id } as TenderRecord;
  for (const c of TENDER_COLUMNS) {
    const v = row[c];
    out[c] = v == null ? "" : String(v);
  }
  return out;
}
