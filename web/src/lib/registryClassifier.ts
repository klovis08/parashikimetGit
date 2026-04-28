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
