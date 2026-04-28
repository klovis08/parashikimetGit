"use client";

import { useState } from "react";

type LabelValue = "relevant" | "not_relevant" | "maybe";

export function FeedbackLabelForm({ tenderId }: { tenderId: number }) {
  const [label, setLabel] = useState<LabelValue>("relevant");
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

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
            placeholder="optional"
          />
        </label>
      </div>
      <label style={{ display: "block" }}>
        Note
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="optional context"
        />
      </label>
      <div className="row" style={{ marginTop: 6 }}>
        <button type="submit" disabled={submitting}>
          {submitting ? "Saving..." : "Save label"}
        </button>
        {status && <span className="meta">{status}</span>}
      </div>
    </form>
  );
}
