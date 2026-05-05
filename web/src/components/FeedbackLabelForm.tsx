"use client";

import { useEffect, useState } from "react";

type LabelValue = "relevant" | "not_relevant" | "maybe";

type SavedLabel = {
  id: number;
  label: LabelValue;
  reviewer: string | null;
  note: string | null;
  timestamp: string;
};

export function FeedbackLabelForm({
  tenderId,
  loadLatestOnMount = false,
  initialLabel = null,
}: {
  tenderId: number;
  loadLatestOnMount?: boolean;
  initialLabel?: {
    label: LabelValue;
    reviewer: string | null;
    note: string | null;
    timestamp: string;
  } | null;
}) {
  const [label, setLabel] = useState<LabelValue>(initialLabel?.label ?? "relevant");
  const [reviewer, setReviewer] = useState(initialLabel?.reviewer ?? "");
  const [note, setNote] = useState(initialLabel?.note ?? "");
  const [status, setStatus] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [loadingLatest, setLoadingLatest] = useState(loadLatestOnMount);

  useEffect(() => {
    if (loadLatestOnMount) return;
    setLabel(initialLabel?.label ?? "relevant");
    setReviewer(initialLabel?.reviewer ?? "");
    setNote(initialLabel?.note ?? "");
  }, [initialLabel, loadLatestOnMount]);

  useEffect(() => {
    if (!loadLatestOnMount) {
      setLoadingLatest(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`/api/tenders/${tenderId}/labels?limit=1`);
        if (!res.ok) return;
        const body = (await res.json()) as { items?: SavedLabel[] };
        const latest = Array.isArray(body.items) ? body.items[0] : undefined;
        if (!latest || cancelled) return;
        setLabel(latest.label);
        setReviewer(latest.reviewer ?? "");
        setNote(latest.note ?? "");
      } catch {
        // Ignore load errors and keep defaults.
      } finally {
        if (!cancelled) setLoadingLatest(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tenderId, loadLatestOnMount]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setStatus("");
    try {
      const res = await fetch(`/api/tenders/${tenderId}/labels`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          label,
          reviewer: reviewer.trim() || null,
          note: note.trim() || null,
        }),
      });
      const body = (await res.json()) as { message?: string };
      if (!res.ok) {
        setStatus(body.message ?? "Label failed");
      } else {
        setStatus("Label saved");
      }
    } catch {
      setStatus("Network error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ marginTop: 8 }}>
      <div className="row">
        <label>
          Analyst label
          <select
            value={label}
            onChange={(e) => setLabel(e.target.value as LabelValue)}
          >
            <option value="relevant">Relevant</option>
            <option value="not_relevant">Not relevant</option>
            <option value="maybe">Maybe</option>
          </select>
        </label>
        <label>
          Reviewer
          <input
            type="text"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
          />
        </label>
      </div>
      <label style={{ display: "block" }}>
        Note
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <div className="row" style={{ marginTop: 6 }}>
        <button type="submit" disabled={submitting || loadingLatest}>
          {submitting ? "Saving..." : "Save label"}
        </button>
        {status && <span className="meta">{status}</span>}
      </div>
    </form>
  );
}
