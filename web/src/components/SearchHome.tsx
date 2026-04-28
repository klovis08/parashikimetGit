"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FeedbackLabelForm } from "./FeedbackLabelForm";

type TenderItem = {
  id: number;
  objekti_procedurave: string;
  autoriteti_kontraktues: string;
  data_publikimit: string;
  ora_publikimit: string;
  fondi_limit_raw: string;
  kodi_cpv_raw: string;
  softwareMeta?: {
    score: number;
    confidence: "high" | "medium" | "low";
    topSignals: string[];
  };
};

type ListResponse = {
  items: TenderItem[];
  page: number;
  pageSize: number;
  total: number;
  pageCount: number;
  sort: string;
  filters: {
    q: string | null;
    authority: string | null;
    cpv: string | null;
    software: string;
    confidence: string | null;
  };
};

type Stats = {
  total: number;
  software_broad: number;
  software_strict: number;
  near_miss: number;
};

function truncateCpv(raw: string, max = 96): string {
  const t = (raw ?? "").replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

export function SearchHome() {
  const [q, setQ] = useState("");
  const [authority, setAuthority] = useState("");
  const [cpv, setCpv] = useState("");
  const [software, setSoftware] = useState<"none" | "broad" | "strict" | "near_miss">(
    "none",
  );
  const [sort, setSort] = useState<"newest" | "oldest">("newest");
  const [confidence, setConfidence] = useState<"any" | "high" | "medium" | "low">("any");
  const [pageSize] = useState(25);

  const [data, setData] = useState<ListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsErr, setStatsErr] = useState<string | null>(null);

  const runFetch = useCallback(
    async (opts: {
      q: string;
      authority: string;
      cpv: string;
      software: "none" | "broad" | "strict" | "near_miss";
      confidence: "any" | "high" | "medium" | "low";
      sort: "newest" | "oldest";
      page: number;
    }) => {
      setLoading(true);
      setError(null);
      const sp = new URLSearchParams();
      if (opts.q.trim()) sp.set("q", opts.q.trim());
      if (opts.authority.trim()) sp.set("authority", opts.authority.trim());
      if (opts.cpv.trim()) sp.set("cpv", opts.cpv.trim());
      if (opts.software !== "none") sp.set("software", opts.software);
      if (opts.confidence !== "any") sp.set("confidence", opts.confidence);
      sp.set("sort", opts.sort);
      sp.set("page", String(opts.page));
      sp.set("pageSize", String(pageSize));
      try {
        const res = await fetch(`/api/tenders?${sp.toString()}`);
        const body = await res.json();
        if (!res.ok) {
          setData(null);
          setError(body.message ?? res.statusText);
          return;
        }
        setData(body as ListResponse);
      } catch {
        setData(null);
        setError("Network error");
      } finally {
        setLoading(false);
      }
    },
    [pageSize],
  );

  useEffect(() => {
    void runFetch({
      q: "",
      authority: "",
      cpv: "",
      software: "none",
      confidence: "any",
      sort: "newest",
      page: 1,
    });
  }, [runFetch]);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/stats");
        const body = await res.json();
        if (!res.ok) {
          setStatsErr(body.message ?? "Stats unavailable");
          return;
        }
        setStats(body as Stats);
      } catch {
        setStatsErr("Stats unavailable");
      }
    })();
  }, []);

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    void runFetch({ q, authority, cpv, software, confidence, sort, page: 1 });
  };

  const goPage = (p: number) => {
    void runFetch({ q, authority, cpv, software, confidence, sort, page: p });
  };

  return (
    <>
      {stats && (
        <p className="sub">
          {stats.total.toLocaleString()} procedura në DB · software broad:{" "}
          {stats.software_broad.toLocaleString()} · strict:{" "}
          {stats.software_strict.toLocaleString()} · near miss:{" "}
          {stats.near_miss.toLocaleString()}
        </p>
      )}
      {statsErr && !stats && (
        <p className="sub" style={{ color: "#8b1a1a" }}>
          {statsErr}
        </p>
      )}

      <div className="panel">
        <form onSubmit={onSearch}>
          <div className="row">
            <label style={{ flex: "1 1 200px" }}>
              Kërkim (objekt, autoritet, CPV)
              <input
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="p.sh. software, portal…"
                autoComplete="off"
              />
            </label>
            <label>
              Autoriteti
              <input
                type="text"
                value={authority}
                onChange={(e) => setAuthority(e.target.value)}
                autoComplete="off"
              />
            </label>
            <label>
              CPV
              <input
                type="text"
                value={cpv}
                onChange={(e) => setCpv(e.target.value)}
                placeholder="prefiks / kod"
                autoComplete="off"
              />
            </label>
            <label>
              Software
              <select
                value={software}
                onChange={(e) =>
                  setSoftware(
                    e.target.value as "none" | "broad" | "strict" | "near_miss",
                  )
                }
              >
                <option value="none">Të gjitha</option>
                <option value="broad">Broad (IT)</option>
                <option value="strict">Strict (pa riparim HW)</option>
                <option value="near_miss">Near misses (review)</option>
              </select>
            </label>
            <label>
              Confidence
              <select
                value={confidence}
                onChange={(e) =>
                  setConfidence(
                    e.target.value as "any" | "high" | "medium" | "low",
                  )
                }
              >
                <option value="any">Të gjitha</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
            <label>
              Renditja
              <select
                value={sort}
                onChange={(e) =>
                  setSort(e.target.value as "newest" | "oldest")
                }
              >
                <option value="newest">Më të rejat sipas publikimit</option>
                <option value="oldest">Më të vjetrat</option>
              </select>
            </label>
            <button type="submit" disabled={loading}>
              {loading ? "…" : "Kërko"}
            </button>
          </div>
        </form>
      </div>

      {error && <div className="err">{error}</div>}

      {data && (
        <>
          <p className="meta">
            {data.total.toLocaleString()} rezultate · faqja {data.page} /{" "}
            {data.pageCount}
          </p>
          {data.items.length === 0 && (
            <p className="meta">Nuk u gjet asgjë me këto filtra.</p>
          )}
          {data.items.map((t) => (
            <article key={t.id} className="card">
              <h2>
                <Link href={`/tenders/${t.id}`}>{t.objekti_procedurave}</Link>
              </h2>
              <p className="line">
                <strong>Autoriteti:</strong> {t.autoriteti_kontraktues}
              </p>
              <p className="line">
                <strong>Publikimi:</strong> {t.data_publikimit}{" "}
                {t.ora_publikimit}
              </p>
              <p className="line">
                <strong>Fondi limit:</strong> {t.fondi_limit_raw || "—"}
              </p>
              <p className="line">
                <strong>CPV:</strong> {truncateCpv(t.kodi_cpv_raw) || "—"}
              </p>
              {t.softwareMeta && (
                <p className="line">
                  <strong>Confidence:</strong> {t.softwareMeta.confidence.toUpperCase()} ·{" "}
                  <strong>Score:</strong> {t.softwareMeta.score}
                  {t.softwareMeta.topSignals.length > 0 && (
                    <>
                      {" "}
                      · <strong>Signals:</strong> {t.softwareMeta.topSignals.slice(0, 2).join(", ")}
                    </>
                  )}
                </p>
              )}
              <FeedbackLabelForm tenderId={t.id} />
            </article>
          ))}

          <div className="pager">
            <button
              type="button"
              disabled={loading || data.page <= 1}
              onClick={() => goPage(data.page - 1)}
            >
              ← Para
            </button>
            <button
              type="button"
              disabled={loading || data.page >= data.pageCount}
              onClick={() => goPage(data.page + 1)}
            >
              Pas →
            </button>
          </div>
        </>
      )}
    </>
  );
}
