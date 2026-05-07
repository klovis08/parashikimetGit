"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
  latestLabel?: {
    label: "relevant" | "not_relevant" | "maybe";
    reviewer: string | null;
    note: string | null;
    timestamp: string;
  } | null;
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
    koha_zhvillimit: string | null;
    reviewer: string | null;
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

type RunbookStatus = "idle" | "running" | "succeeded" | "failed";

type RunbookState = {
  id: string;
  status: RunbookStatus;
  command: string;
  cwd: string;
  startedAt: string | null;
  finishedAt: string | null;
  exitCode: number | null;
  signal: string | null;
  outputTail: string[];
  message: string | null;
  enabled: boolean;
};

type SearchOpts = {
  q: string;
  authority: string;
  cpv: string;
  kohaZhvillimit: string;
  reviewer: string;
  software: "none" | "broad" | "strict" | "near_miss";
  confidence: "any" | "high" | "medium" | "low";
  sort: "newest" | "oldest";
  page: number;
};

function truncateCpv(raw: string, max = 96): string {
  const t = (raw ?? "").replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

export function SearchHome() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const initialQ = searchParams.get("q") ?? "";
  const initialAuthority = searchParams.get("authority") ?? "";
  const initialCpv = searchParams.get("cpv") ?? "";
  const initialKohaZhvillimit = searchParams.get("koha_zhvillimit") ?? "";
  const initialReviewer = searchParams.get("reviewer") ?? "";
  const initialSoftware: SearchOpts["software"] = (() => {
    const raw = searchParams.get("software");
    return raw === "broad" || raw === "strict" || raw === "near_miss" ? raw : "none";
  })();
  const initialSort: SearchOpts["sort"] = searchParams.get("sort") === "oldest" ? "oldest" : "newest";
  const initialConfidence: SearchOpts["confidence"] = (() => {
    const raw = searchParams.get("confidence");
    return raw === "high" || raw === "medium" || raw === "low" ? raw : "any";
  })();
  const initialPage = (() => {
    const n = Number(searchParams.get("page") ?? "1");
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 1;
  })();

  const [q, setQ] = useState(initialQ);
  const [authority, setAuthority] = useState(initialAuthority);
  const [cpv, setCpv] = useState(initialCpv);
  const [kohaZhvillimit, setKohaZhvillimit] = useState(initialKohaZhvillimit);
  const [reviewer, setReviewer] = useState(initialReviewer);
  const [software, setSoftware] = useState<"none" | "broad" | "strict" | "near_miss">(initialSoftware);
  const [sort, setSort] = useState<"newest" | "oldest">(initialSort);
  const [confidence, setConfidence] = useState<"any" | "high" | "medium" | "low">(initialConfidence);
  const [currentPage, setCurrentPage] = useState(initialPage);
  const [pageSize] = useState(25);
  const initialFetchParamsRef = useRef<SearchOpts>({
    q: initialQ,
    authority: initialAuthority,
    cpv: initialCpv,
    kohaZhvillimit: initialKohaZhvillimit,
    reviewer: initialReviewer,
    software: initialSoftware,
    confidence: initialConfidence,
    sort: initialSort,
    page: initialPage,
  });

  const [data, setData] = useState<ListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsErr, setStatsErr] = useState<string | null>(null);
  const [runbook, setRunbook] = useState<RunbookState | null>(null);
  const [runbookErr, setRunbookErr] = useState<string | null>(null);
  const [runbookBusy, setRunbookBusy] = useState(false);

  const buildParams = useCallback(
    (opts: SearchOpts) => {
      const sp = new URLSearchParams();
      if (opts.q.trim()) sp.set("q", opts.q.trim());
      if (opts.authority.trim()) sp.set("authority", opts.authority.trim());
      if (opts.cpv.trim()) sp.set("cpv", opts.cpv.trim());
      if (opts.kohaZhvillimit.trim()) {
        sp.set("koha_zhvillimit", opts.kohaZhvillimit.trim());
      }
      if (opts.reviewer.trim()) sp.set("reviewer", opts.reviewer.trim());
      if (opts.software !== "none") sp.set("software", opts.software);
      if (opts.confidence !== "any") sp.set("confidence", opts.confidence);
      sp.set("sort", opts.sort);
      sp.set("page", String(opts.page));
      sp.set("pageSize", String(pageSize));
      return sp;
    },
    [pageSize],
  );

  const runFetch = useCallback(
    async (opts: SearchOpts) => {
      setLoading(true);
      setError(null);
      setCurrentPage(opts.page);
      const sp = buildParams(opts);
      router.replace(`${pathname}?${sp.toString()}`, { scroll: false });
      try {
        const res = await fetch(`/api/tenders?${sp.toString()}`);
        const body = await res.json();
        if (!res.ok) {
          setData(null);
          setError(body.message ?? res.statusText);
          return;
        }
        setData(body as ListResponse);
        setCurrentPage((body as ListResponse).page);
      } catch {
        setData(null);
        setError("Network error");
      } finally {
        setLoading(false);
      }
    },
    [buildParams, pathname, router],
  );

  useEffect(() => {
    void runFetch(initialFetchParamsRef.current);
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

  const refreshRunbook = useCallback(async () => {
    try {
      const res = await fetch("/api/runbook");
      const body = (await res.json()) as RunbookState;
      if (!res.ok) {
        setRunbookErr("Runbook status unavailable");
        return;
      }
      setRunbook(body);
      setRunbookErr(null);
    } catch {
      setRunbookErr("Runbook status unavailable");
    }
  }, []);

  useEffect(() => {
    void refreshRunbook();
  }, [refreshRunbook]);

  useEffect(() => {
    if (runbook?.status !== "running") return;
    const timer = window.setInterval(() => {
      void refreshRunbook();
    }, 5000);
    return () => {
      window.clearInterval(timer);
    };
  }, [refreshRunbook, runbook?.status]);

  const triggerRunbook = async () => {
    setRunbookBusy(true);
    setRunbookErr(null);
    try {
      const res = await fetch("/api/runbook", { method: "POST" });
      const body = (await res.json()) as {
        run?: RunbookState;
        message?: string;
      };
      if (!res.ok) {
        if (body.run) setRunbook(body.run);
        setRunbookErr(body.message ?? "Runbook trigger failed");
        return;
      }
      if (!body.run) {
        setRunbookErr("Runbook trigger failed");
        return;
      }
      setRunbook(body.run);
    } catch {
      setRunbookErr("Runbook trigger failed");
    } finally {
      setRunbookBusy(false);
    }
  };

  const runbookMeta = useMemo(() => {
    if (!runbook) return "...";
    if (!runbook.enabled) {
      return "trigger disabled.";
    }
    if (runbook.status === "running") {
      return `executing (${runbook.startedAt ?? "tani"}).`;
    }
    if (runbook.status === "succeeded") {
      return `success (${runbook.finishedAt ?? "pa timestamp"}).`;
    }
    if (runbook.status === "failed") {
      return `failed (${runbook.finishedAt ?? "pa timestamp"}).`;
    }
    return "-";
  }, [runbook]);

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    void runFetch({
      q,
      authority,
      cpv,
      kohaZhvillimit,
      reviewer,
      software,
      confidence,
      sort,
      page: 1,
    });
  };

  const goPage = (p: number) => {
    void runFetch({
      q,
      authority,
      cpv,
      kohaZhvillimit,
      reviewer,
      software,
      confidence,
      sort,
      page: p,
    });
  };

  const detailSearchQuery = useMemo(() => {
    return buildParams({
      q,
      authority,
      cpv,
      kohaZhvillimit,
      reviewer,
      software,
      confidence,
      sort,
      page: data?.page ?? currentPage,
    }).toString();
  }, [
    authority,
    buildParams,
    confidence,
    cpv,
    currentPage,
    data?.page,
    kohaZhvillimit,
    q,
    reviewer,
    software,
    sort,
  ]);

  return (
    <>
      <div className="panel">
        <div className="row">
          <button
            type="button"
            disabled={!runbook?.enabled || runbookBusy || runbook?.status === "running"}
            onClick={() => {
              void triggerRunbook();
            }}
          >
            {runbookBusy || runbook?.status === "running"
              ? "Runbook në progres…"
              : "Run ingest/scrape manualisht"}
          </button>
        </div>
        <p className="meta">{runbookMeta}</p>
        {runbook?.message && <p className="meta">Detaj: {runbook.message}</p>}
        {runbookErr && (
          <p className="meta" style={{ color: "#8b1a1a" }}>
            {runbookErr}
          </p>
        )}
      </div>

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
                autoComplete="off"
              />
            </label>
            <label>
              Muaji (koha_zhvillimit)
              <input
                type="text"
                value={kohaZhvillimit}
                onChange={(e) => setKohaZhvillimit(e.target.value)}
                autoComplete="off"
              />
            </label>
            <label>
              Reviewer
              <input
                type="text"
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                placeholder="p.sh. emri i analistit"
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
                <Link href={`/tenders/${t.id}?${detailSearchQuery}`}>{t.objekti_procedurave}</Link>
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
              <FeedbackLabelForm
                tenderId={t.id}
                loadLatestOnMount={false}
                initialLabel={t.latestLabel ?? null}
              />
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
