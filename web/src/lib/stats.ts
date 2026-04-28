import { getDb, rowToTenderRecord } from "./db";
import {
  classifyNearMiss,
  classifySoftwareBroad,
  classifySoftwareStrict,
} from "./registryClassifier";
import { SELECT_LIST } from "./tenderColumns";

export interface RegistryStats {
  total: number;
  software_broad: number;
  software_strict: number;
  near_miss: number;
}

export function computeRegistryStats(): RegistryStats {
  const db = getDb();
  const total = Number(
    (db.prepare("SELECT COUNT(*) as n FROM tenders").get() as { n: number }).n,
  );
  let software_broad = 0;
  let software_strict = 0;
  let near_miss = 0;
  const rows = db
    .prepare(`SELECT ${SELECT_LIST} FROM tenders`);
  for (const row of rows.iterate() as Iterable<Record<string, unknown>>) {
    const rec = rowToTenderRecord(row);
    if (classifySoftwareBroad(rec).ok) software_broad += 1;
    if (classifySoftwareStrict(rec).ok) software_strict += 1;
    if (classifyNearMiss(rec).ok) near_miss += 1;
  }
  return { total, software_broad, software_strict, near_miss };
}
