import type { SoftwareFilterMode, SortKey, TendersQuery } from "./queryTenders";
import type { ConfidenceTier } from "./registryClassifier";

const PAGE_SIZE_DEFAULT = 25;
const PAGE_SIZE_MAX = 100;
const REVIEWER_FILTER_MAX = 120;

export interface ParsedTendersQuery {
  ok: true;
  value: TendersQuery;
}

export interface ParseError {
  ok: false;
  error: string;
}

export type ParseTendersResult = ParsedTendersQuery | ParseError;

function parseSoftware(raw: string | null): SoftwareFilterMode | ParseError {
  if (raw == null || raw === "" || raw.toLowerCase() === "none") {
    return "none";
  }
  const l = raw.toLowerCase();
  if (l === "broad" || l === "strict" || l === "near_miss") return l;
  return { ok: false, error: 'software must be "none", "broad", "strict", or "near_miss"' };
}

function parseSort(raw: string | null): SortKey | ParseError {
  if (raw == null || raw === "") return "publication_desc";
  const l = raw.toLowerCase();
  if (
    l === "newest" ||
    l === "publication_desc" ||
    l === "desc" ||
    l === "data_desc"
  ) {
    return "publication_desc";
  }
  if (
    l === "oldest" ||
    l === "publication_asc" ||
    l === "asc" ||
    l === "data_asc"
  ) {
    return "publication_asc";
  }
  return { ok: false, error: "invalid sort (use newest or oldest)" };
}

function parseConfidence(raw: string | null): ConfidenceTier | undefined | ParseError {
  if (raw == null || raw === "" || raw.toLowerCase() === "any") return undefined;
  const l = raw.toLowerCase();
  if (l === "high" || l === "medium" || l === "low") return l;
  return { ok: false, error: 'confidence must be "high", "medium", "low", or "any"' };
}

function isParseError(x: unknown): x is ParseError {
  return typeof x === "object" && x !== null && "ok" in x && (x as ParseError).ok === false;
}

export function parseTendersSearchParams(
  sp: URLSearchParams,
): ParseTendersResult {
  const q = sp.get("q") ?? undefined;
  const authority = sp.get("authority") ?? undefined;
  const cpv = sp.get("cpv") ?? undefined;
  const kohaZhvillimit = sp.get("koha_zhvillimit") ?? undefined;
  const reviewerRaw = sp.get("reviewer");
  const reviewer =
    reviewerRaw == null || reviewerRaw.trim() === ""
      ? undefined
      : reviewerRaw.trim().slice(0, REVIEWER_FILTER_MAX);

  const softwareRaw = parseSoftware(sp.get("software"));
  if (isParseError(softwareRaw)) return softwareRaw;

  const sortRaw = parseSort(sp.get("sort"));
  if (isParseError(sortRaw)) return sortRaw;
  const confidenceRaw = parseConfidence(sp.get("confidence"));
  if (isParseError(confidenceRaw)) return confidenceRaw;

  const page = parseInt(sp.get("page") ?? "1", 10);
  if (Number.isNaN(page) || page < 1) {
    return { ok: false, error: "page must be a positive integer" };
  }

  let pageSize = parseInt(
    sp.get("pageSize") ?? String(PAGE_SIZE_DEFAULT),
    10,
  );
  if (Number.isNaN(pageSize) || pageSize < 1) {
    return { ok: false, error: "pageSize must be a positive integer" };
  }
  if (pageSize > PAGE_SIZE_MAX) {
    pageSize = PAGE_SIZE_MAX;
  }

  return {
    ok: true,
    value: {
      q,
      authority,
      cpv,
      kohaZhvillimit,
      reviewer,
      software: softwareRaw,
      page,
      pageSize,
      sort: sortRaw,
      confidence: confidenceRaw,
    },
  };
}
