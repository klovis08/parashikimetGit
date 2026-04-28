export type AnalystLabelValue = "relevant" | "not_relevant" | "maybe";

export interface LabelPayload {
  label: AnalystLabelValue;
  reviewer: string | null;
  note: string | null;
}

export function parseLabelPayload(raw: unknown): LabelPayload | { error: string } {
  if (!raw || typeof raw !== "object") {
    return { error: "payload must be an object" };
  }
  const maybe = raw as Record<string, unknown>;
  const label = String(maybe.label ?? "").trim();
  if (label !== "relevant" && label !== "not_relevant" && label !== "maybe") {
    return { error: 'label must be "relevant", "not_relevant", or "maybe"' };
  }
  const reviewerRaw = maybe.reviewer;
  const reviewer =
    reviewerRaw == null || String(reviewerRaw).trim() === ""
      ? null
      : String(reviewerRaw).trim().slice(0, 120);
  const noteRaw = maybe.note;
  const note =
    noteRaw == null || String(noteRaw).trim() === ""
      ? null
      : String(noteRaw).trim().slice(0, 1000);
  return { label, reviewer, note };
}
