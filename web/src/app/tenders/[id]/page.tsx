import Link from "next/link";
import { Fragment } from "react";
import { notFound } from "next/navigation";
import { dbAvailable } from "@/lib/db";
import { getTenderDetailById } from "@/lib/queryTenders";
import {
  classifySoftwareBroad,
  classifySoftwareStrict,
} from "@/lib/registryClassifier";
import { FeedbackLabelForm } from "@/components/FeedbackLabelForm";

export const dynamic = "force-dynamic";

const LABELS: Record<string, string> = {
  id: "ID",
  source_hash: "Source hash",
  objekti_procedurave: "Objekti i procedurës",
  autoriteti_kontraktues: "Autoriteti kontraktues",
  burimi_financimit: "Burimi i financimit",
  fondi_limit_raw: "Fondi limit (raw)",
  fondi_limit_lek: "Fondi limit (lek)",
  data_publikimit: "Data e publikimit",
  ora_publikimit: "Ora e publikimit",
  data_iso: "Data (ISO)",
  viti: "Viti",
  koha_zhvillimit: "Koha e zhvillimit",
  kodi_cpv_raw: "Kodi CPV (raw)",
  cpv_spans: "CPV spans",
  tipi_procedures: "Tipi i procedurës",
  anulluar: "Anuluar",
  page_fetched: "Faqja e shkarkuar",
  row_index_on_page: "Indeksi në faqe",
  first_seen_at: "Parë herë",
  last_seen_at: "Përditësuar",
};

export default async function TenderDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  if (!dbAvailable()) {
    return (
      <main>
        <p className="err">
          Baza e të dhënave nuk lexohet. Vendos REGISTRY_DB_PATH në mjedis.
        </p>
        <Link href="/">← Kthehu</Link>
      </main>
    );
  }

  const { id: raw } = await params;
  const id = Number(raw);
  if (!Number.isFinite(id) || id < 1) notFound();

  const row = getTenderDetailById(id);
  if (!row) notFound();

  const classifierInput = {
    objekti_procedurave: String(row.objekti_procedurave ?? ""),
    kodi_cpv_raw: String(row.kodi_cpv_raw ?? ""),
    tipi_procedures: String(row.tipi_procedures ?? ""),
  };
  const broad = classifySoftwareBroad(classifierInput);
  const strict = classifySoftwareStrict(classifierInput);

  const keys = Object.keys(row).sort((a, b) => {
    const oa = LABELS[a] ? 0 : 1;
    const ob = LABELS[b] ? 0 : 1;
    if (oa !== ob) return oa - ob;
    return a.localeCompare(b);
  });

  return (
    <main>
      <Link href="/" className="back">
        ← Kërkim
      </Link>
      <h1>{String(row.objekti_procedurave ?? "")}</h1>
      <p className="sub">
        Klasifikim software (i njëjtë me pipeline): broad{" "}
        {broad.ok ? "po" : "jo"} · strict {strict.ok ? "po" : "jo"}
        {strict.excludedReasons.length > 0 && (
          <>
            {" "}
            (jashtë strict: {strict.excludedReasons.join("; ")})
          </>
        )}
      </p>
      <div className="panel">
        <FeedbackLabelForm tenderId={id} />
      </div>

      <div className="panel">
        <dl className="detail">
          {keys.map((k) => (
            <Fragment key={k}>
              <dt>{LABELS[k] ?? k}</dt>
              <dd>
                {row[k] === null || row[k] === ""
                  ? "—"
                  : String(row[k])}
              </dd>
            </Fragment>
          ))}
        </dl>
      </div>
    </main>
  );
}
