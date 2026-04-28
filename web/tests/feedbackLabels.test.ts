import test from "node:test";
import assert from "node:assert/strict";
import { parseLabelPayload } from "../src/lib/feedbackLabelsPayload.ts";

test("parseLabelPayload accepts valid payload", () => {
  const out = parseLabelPayload({
    label: "relevant",
    reviewer: "qa-user",
    note: "matches software scope",
  });
  assert.ok(!("error" in out));
  if ("error" in out) return;
  assert.equal(out.label, "relevant");
  assert.equal(out.reviewer, "qa-user");
});

test("parseLabelPayload rejects invalid labels", () => {
  const out = parseLabelPayload({ label: "unknown" });
  assert.ok("error" in out);
});

test("parseLabelPayload trims optional fields to null", () => {
  const out = parseLabelPayload({ label: "maybe", reviewer: " ", note: "" });
  assert.ok(!("error" in out));
  if ("error" in out) return;
  assert.equal(out.reviewer, null);
  assert.equal(out.note, null);
});
