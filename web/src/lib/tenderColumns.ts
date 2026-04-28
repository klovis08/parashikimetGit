/** Canonical tender columns (matches registry_parse.COLUMNS + DB id). */
export const TENDER_COLUMNS = [
  "objekti_procedurave",
  "autoriteti_kontraktues",
  "burimi_financimit",
  "fondi_limit_raw",
  "fondi_limit_lek",
  "data_publikimit",
  "ora_publikimit",
  "data_iso",
  "viti",
  "koha_zhvillimit",
  "kodi_cpv_raw",
  "cpv_spans",
  "tipi_procedures",
  "anulluar",
  "page_fetched",
  "row_index_on_page",
] as const;

export type TenderColumn = (typeof TENDER_COLUMNS)[number];

export type TenderRecord = { id: number } & Record<TenderColumn, string>;

export const SELECT_LIST = `id, ${TENDER_COLUMNS.join(", ")}`;
