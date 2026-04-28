/**
 * Port of registry_classifier.py — keep in sync with Python for broad/strict parity.
 * Tradeoff: duplicated logic; run export_registry.py validate periodically against DB.
 */

import fs from "node:fs";
import path from "node:path";

type ClassifierRules = {
  include_keyword_patterns: string[];
  include_cpv_prefixes: string[];
  exclude_keyword_patterns: string[];
  exclude_cpv_prefixes: string[];
  near_miss_keyword_patterns: string[];
  near_miss_cpv_prefixes: string[];
  scoring: {
    scale: { min: number; max: number };
    weights: {
      broad_bonus: number;
      strict_bonus: number;
      include_keyword_hit: number;
      include_cpv_hit: number;
      exclude_keyword_hit: number;
      exclude_cpv_hit: number;
      mixed_bundle_bonus: number;
      near_keyword_hit: number;
      near_cpv_hit: number;
    };
    confidence_thresholds: {
      high: number;
      medium: number;
    };
    top_signal_count: number;
  };
};

function loadRules(): ClassifierRules {
  const rulesPath = path.resolve(process.cwd(), "../classifier_rules.json");
  return JSON.parse(fs.readFileSync(rulesPath, "utf-8")) as ClassifierRules;
}

const CLASSIFIER_RULES = loadRules();
const MOJIBAKE_FIXES: Record<string, string> = {
  "Ã«": "e",
  "Ã§": "c",
  "Ã‰": "e",
  "â€™": "'",
  "â€œ": '"',
  "â€": '"',
  "â€“": "-",
  "â€”": "-",
  "�": "",
};

function norm(value: string | null | undefined): string {
  let text = value ?? "";
  for (const [wrong, fixed] of Object.entries(MOJIBAKE_FIXES)) {
    text = text.replaceAll(wrong, fixed);
  }
  text = text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  return text.trim().replace(/\s+/g, " ");
}

export function parseCpvCodes(cpvText: string): string[] {
  const m = (cpvText ?? "").match(/\b\d{8}-\d\b/g);
  return m ?? [];
}

let keywordRegex: RegExp | null = null;
let excludeRegex: RegExp | null = null;

function keywordRegexCached(): RegExp {
  if (!keywordRegex) {
    keywordRegex = new RegExp(CLASSIFIER_RULES.include_keyword_patterns.join("|"), "gi");
  }
  return keywordRegex;
}

function excludeRegexCached(): RegExp {
  if (!excludeRegex) {
    excludeRegex = new RegExp(CLASSIFIER_RULES.exclude_keyword_patterns.join("|"), "gi");
  }
  return excludeRegex;
}

let nearMissRegex: RegExp | null = null;
function nearMissRegexCached(): RegExp {
  if (!nearMissRegex) {
    nearMissRegex = new RegExp(CLASSIFIER_RULES.near_miss_keyword_patterns.join("|"), "gi");
  }
  return nearMissRegex;
}

function combinedText(record: ClassifierFields): string {
  return norm(
    [
      record.objekti_procedurave ?? "",
      record.kodi_cpv_raw ?? "",
      record.tipi_procedures ?? "",
    ].join(" "),
  );
}

function keywordHits(text: string, regex: RegExp): string[] {
  const reasons: string[] = [];
  regex.lastIndex = 0;
  let m: RegExpExecArray | null;
  const r = new RegExp(regex.source, regex.flags);
  while ((m = r.exec(text)) !== null) {
    const token = m[0];
    if (token) {
      const label = `kw:${token}`;
      if (!reasons.includes(label)) reasons.push(label);
    }
  }
  return reasons;
}

function cpvInclusionReasons(cpvText: string): string[] {
  const reasons: string[] = [];
  for (const cpv of parseCpvCodes(cpvText)) {
    const digits = cpv.split("-")[0] ?? "";
    if (CLASSIFIER_RULES.include_cpv_prefixes.some((prefix) => digits.startsWith(prefix))) {
      const label = `cpv:${cpv}`;
      if (!reasons.includes(label)) reasons.push(label);
    }
  }
  return reasons;
}

function cpvExclusionReasons(cpvText: string): string[] {
  const reasons: string[] = [];
  for (const cpv of parseCpvCodes(cpvText)) {
    const digits = cpv.split("-")[0] ?? "";
    if (CLASSIFIER_RULES.exclude_cpv_prefixes.some((prefix) => digits.startsWith(prefix))) {
      const label = `exclude_cpv:${cpv}`;
      if (!reasons.includes(label)) reasons.push(label);
    }
  }
  return reasons;
}

function cpvNearMissReasons(cpvText: string): string[] {
  const reasons: string[] = [];
  for (const cpv of parseCpvCodes(cpvText)) {
    const digits = cpv.split("-")[0] ?? "";
    if (CLASSIFIER_RULES.near_miss_cpv_prefixes.some((prefix) => digits.startsWith(prefix))) {
      const label = `near_cpv:${cpv}`;
      if (!reasons.includes(label)) reasons.push(label);
    }
  }
  return reasons;
}

function excludeKeywordHits(text: string, regex: RegExp): string[] {
  const reasons: string[] = [];
  const r = new RegExp(regex.source, regex.flags);
  let m: RegExpExecArray | null;
  while ((m = r.exec(text)) !== null) {
    const token = m[0];
    if (token) {
      const label = `exclude_kw:${token}`;
      if (!reasons.includes(label)) reasons.push(label);
    }
  }
  return reasons;
}

export type ClassifierFields = {
  objekti_procedurave?: string | null;
  kodi_cpv_raw?: string | null;
  tipi_procedures?: string | null;
};

export type ConfidenceTier = "high" | "medium" | "low";

export function classifySoftwareBroad(
  record: ClassifierFields,
): { ok: boolean; reasons: string[] } {
  const text = combinedText(record as Record<string, string>);
  const regex = keywordRegexCached();
  const reasons = keywordHits(text, regex);
  for (const r of cpvInclusionReasons(record.kodi_cpv_raw ?? "")) {
    if (!reasons.includes(r)) reasons.push(r);
  }
  return { ok: reasons.length > 0, reasons };
}

export function hardwareRepairExclusionSignals(
  record: ClassifierFields,
): { ok: boolean; reasons: string[] } {
  const text = combinedText(record);
  const reasons = excludeKeywordHits(text, excludeRegexCached());
  for (const r of cpvExclusionReasons(record.kodi_cpv_raw ?? "")) {
    if (!reasons.includes(r)) reasons.push(r);
  }
  return { ok: reasons.length > 0, reasons };
}

export function classifySoftwareStrict(record: ClassifierFields): {
  ok: boolean;
  broadReasons: string[];
  excludedReasons: string[];
} {
  const { ok: broadOk, reasons: broadReasons } = classifySoftwareBroad(record);
  if (!broadOk) {
    return { ok: false, broadReasons: [], excludedReasons: [] };
  }
  const { ok: excludedOk, reasons: excludedReasons } =
    hardwareRepairExclusionSignals(record);
  if (excludedOk) {
    return { ok: false, broadReasons, excludedReasons };
  }
  return { ok: true, broadReasons, excludedReasons: [] };
}

export function mixedItBundleSignal(
  record: ClassifierFields,
): { ok: boolean; reasons: string[] } {
  const broad = classifySoftwareBroad(record);
  const excluded = hardwareRepairExclusionSignals(record);
  if (broad.ok && excluded.ok) {
    return { ok: true, reasons: [...broad.reasons, ...excluded.reasons] };
  }
  return { ok: false, reasons: [] };
}

export function classifyNearMiss(
  record: ClassifierFields,
): { ok: boolean; reasons: string[] } {
  const strict = classifySoftwareStrict(record);
  if (strict.ok) {
    return { ok: false, reasons: [] };
  }

  const mixed = mixedItBundleSignal(record);
  if (mixed.ok) {
    return {
      ok: true,
      reasons: mixed.reasons.map((reason) => `mixed_it_bundle:${reason}`),
    };
  }

  const broad = classifySoftwareBroad(record);
  if (broad.ok) {
    return { ok: false, reasons: [] };
  }

  const reasons: string[] = [];
  const text = combinedText(record);
  const nearRegex = new RegExp(nearMissRegexCached().source, nearMissRegexCached().flags);
  let m: RegExpExecArray | null;
  while ((m = nearRegex.exec(text)) !== null) {
    const token = m[0];
    const label = `near_kw:${token}`;
    if (!reasons.includes(label)) reasons.push(label);
  }
  for (const r of cpvNearMissReasons(record.kodi_cpv_raw ?? "")) {
    if (!reasons.includes(r)) reasons.push(r);
  }
  return { ok: reasons.length > 0, reasons };
}

export function matchesSoftwareFilter(
  record: ClassifierFields,
  mode: "broad" | "strict" | "near_miss",
): boolean {
  if (mode === "broad") {
    return classifySoftwareBroad(record).ok;
  }
  if (mode === "near_miss") {
    return classifyNearMiss(record).ok;
  }
  return classifySoftwareStrict(record).ok;
}

function confidenceFromScore(score: number): ConfidenceTier {
  const thresholds = CLASSIFIER_RULES.scoring.confidence_thresholds;
  if (score >= thresholds.high) return "high";
  if (score >= thresholds.medium) return "medium";
  return "low";
}

function scoreReasonEntries(reasons: string[], weight: number): Array<[string, number]> {
  return reasons.map((reason) => [reason, weight]);
}

export function classifySoftwareScored(record: ClassifierFields): {
  score: number;
  confidence: ConfidenceTier;
  topSignals: string[];
  broad: { ok: boolean; reasons: string[] };
  strict: { ok: boolean; broadReasons: string[]; excludedReasons: string[] };
  nearMiss: { ok: boolean; reasons: string[] };
  mixed: { ok: boolean; reasons: string[] };
  exclusion: { ok: boolean; reasons: string[] };
} {
  const broad = classifySoftwareBroad(record);
  const strict = classifySoftwareStrict(record);
  const nearMiss = classifyNearMiss(record);
  const mixed = mixedItBundleSignal(record);
  const exclusion = hardwareRepairExclusionSignals(record);
  const scoring = CLASSIFIER_RULES.scoring;
  const weights = scoring.weights;

  const includeKwReasons = broad.reasons.filter((r) => r.startsWith("kw:"));
  const includeCpvReasons = broad.reasons.filter((r) => r.startsWith("cpv:"));
  const excludeKwReasons = exclusion.reasons.filter((r) => r.startsWith("exclude_kw:"));
  const excludeCpvReasons = exclusion.reasons.filter((r) => r.startsWith("exclude_cpv:"));
  const nearKwReasons = nearMiss.reasons.filter((r) => r.startsWith("near_kw:"));
  const nearCpvReasons = nearMiss.reasons.filter((r) => r.startsWith("near_cpv:"));
  const mixedSignalReasons = nearMiss.reasons.filter((r) => r.startsWith("mixed_it_bundle:"));

  const signalEntries: Array<[string, number]> = [];
  const summaryEntries: Array<[string, number]> = [];
  if (broad.ok) {
    signalEntries.push(["status:broad", weights.broad_bonus]);
    summaryEntries.push(["status:broad", weights.broad_bonus]);
  }
  if (strict.ok) {
    signalEntries.push(["status:strict", weights.strict_bonus]);
    summaryEntries.push(["status:strict", weights.strict_bonus]);
  }
  if (mixed.ok) {
    signalEntries.push(["status:mixed_it_bundle", weights.mixed_bundle_bonus]);
    summaryEntries.push(["status:mixed_it_bundle", weights.mixed_bundle_bonus]);
  }
  signalEntries.push(...scoreReasonEntries(includeKwReasons, weights.include_keyword_hit));
  if (includeKwReasons.length > 0) {
    summaryEntries.push(["include_kw_hits", includeKwReasons.length * weights.include_keyword_hit]);
  }
  signalEntries.push(...scoreReasonEntries(includeCpvReasons, weights.include_cpv_hit));
  if (includeCpvReasons.length > 0) {
    summaryEntries.push(["include_cpv_hits", includeCpvReasons.length * weights.include_cpv_hit]);
  }
  signalEntries.push(...scoreReasonEntries(excludeKwReasons, weights.exclude_keyword_hit));
  if (excludeKwReasons.length > 0) {
    summaryEntries.push(["exclude_kw_hits", excludeKwReasons.length * weights.exclude_keyword_hit]);
  }
  signalEntries.push(...scoreReasonEntries(excludeCpvReasons, weights.exclude_cpv_hit));
  if (excludeCpvReasons.length > 0) {
    summaryEntries.push(["exclude_cpv_hits", excludeCpvReasons.length * weights.exclude_cpv_hit]);
  }
  signalEntries.push(...scoreReasonEntries(nearKwReasons, weights.near_keyword_hit));
  if (nearKwReasons.length > 0) {
    summaryEntries.push(["near_kw_hits", nearKwReasons.length * weights.near_keyword_hit]);
  }
  signalEntries.push(...scoreReasonEntries(nearCpvReasons, weights.near_cpv_hit));
  if (nearCpvReasons.length > 0) {
    summaryEntries.push(["near_cpv_hits", nearCpvReasons.length * weights.near_cpv_hit]);
  }
  signalEntries.push(...scoreReasonEntries(mixedSignalReasons, weights.mixed_bundle_bonus));
  if (mixedSignalReasons.length > 0) {
    summaryEntries.push(["mixed_near_hits", mixedSignalReasons.length * weights.mixed_bundle_bonus]);
  }

  const rawScore = signalEntries.reduce((sum, [, weight]) => sum + weight, 0);
  const score = Math.max(scoring.scale.min, Math.min(scoring.scale.max, rawScore));
  const confidence = confidenceFromScore(score);

  const topSignals = [...summaryEntries]
    .sort((a, b) => {
      const byAbs = Math.abs(b[1]) - Math.abs(a[1]);
      if (byAbs !== 0) return byAbs;
      if (b[1] !== a[1]) return b[1] - a[1];
      return a[0].localeCompare(b[0]);
    })
    .slice(0, scoring.top_signal_count)
    .map(([signal, weight]) => `${signal}(${weight >= 0 ? "+" : ""}${weight})`);

  return { score, confidence, topSignals, broad, strict, nearMiss, mixed, exclusion };
}
