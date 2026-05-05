import test from "node:test";
import assert from "node:assert/strict";
import { parseTendersSearchParams } from "../src/lib/parseTendersParams.ts";

test("parseTendersSearchParams parses valid filters", () => {
  const sp = new URLSearchParams({
    q: "software",
    authority: "AK",
    cpv: "72",
    koha_zhvillimit: "prill",
    reviewer: "ana",
    software: "strict",
    page: "2",
    pageSize: "50",
    sort: "oldest",
  });
  const parsed = parseTendersSearchParams(sp);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  assert.equal(parsed.value.software, "strict");
  assert.equal(parsed.value.kohaZhvillimit, "prill");
  assert.equal(parsed.value.reviewer, "ana");
  assert.equal(parsed.value.page, 2);
  assert.equal(parsed.value.pageSize, 50);
  assert.equal(parsed.value.sort, "publication_asc");
});

test("parseTendersSearchParams rejects invalid software value", () => {
  const sp = new URLSearchParams({ software: "invalid" });
  const parsed = parseTendersSearchParams(sp);
  assert.equal(parsed.ok, false);
});

test("parseTendersSearchParams supports near_miss software mode", () => {
  const sp = new URLSearchParams({ software: "near_miss" });
  const parsed = parseTendersSearchParams(sp);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  assert.equal(parsed.value.software, "near_miss");
});

test("parseTendersSearchParams caps pageSize to max", () => {
  const sp = new URLSearchParams({ pageSize: "5000" });
  const parsed = parseTendersSearchParams(sp);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  assert.equal(parsed.value.pageSize, 100);
});

test("parseTendersSearchParams parses confidence filter", () => {
  const sp = new URLSearchParams({ confidence: "medium" });
  const parsed = parseTendersSearchParams(sp);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  assert.equal(parsed.value.confidence, "medium");
});

test("parseTendersSearchParams rejects invalid confidence filter", () => {
  const sp = new URLSearchParams({ confidence: "urgent" });
  const parsed = parseTendersSearchParams(sp);
  assert.equal(parsed.ok, false);
});

test("parseTendersSearchParams omits reviewer when blank", () => {
  const sp = new URLSearchParams({ reviewer: "   " });
  const parsed = parseTendersSearchParams(sp);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  assert.equal(parsed.value.reviewer, undefined);
});
