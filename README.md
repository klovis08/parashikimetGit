# Parashikimet Tender Pipeline

Scraper + classification system

## Repository layout

- `ingest_registry.py`: scrape ingest entrypoint (`daily` / `bootstrap`)
- `registry_store.py`: SQLite schema and deduplicating upsert logic
- `export_registry.py`: canonical and software-filtered CSV exports + validation
- `registry_classifier.py`: software relevance rules (broad/strict/near-miss)
- `run_registry_pipeline.py`: production orchestration for ingest/export/validate
- `tests/`: Python unit tests
- `web/`: Next.js UI and API over `registry.db`
- `ops/RUNBOOK.md`: deployment and operations runbook

## Quick start

### 1) Python environment

```bash
python -m pip install -r requirements.txt
```

### 2) Build database from existing full CSV (fast path)

If `registry_2026_full.csv` already exists and you want to avoid a full crawl,
load it directly into SQLite:

```bash
python -c "import csv; from registry_store import connect, init_schema, upsert_tenders; from registry_parse import COLUMNS; conn=connect('registry.db'); init_schema(conn); rows=list(csv.DictReader(open('registry_2026_full.csv', encoding='utf-8-sig', newline=''))); rows=[{k:(r.get(k,'') or '') for k in COLUMNS} for r in rows]; st=upsert_tenders(conn, rows); conn.commit(); print({'inserted': st.rows_inserted, 'duplicates': st.duplicates_skipped}); conn.close()"
```

### 3) Export full + software subsets

```bash
python export_registry.py export --db registry.db --year 2026 --out-dir .
python export_registry.py validate --db registry.db --json
```

### 4) Run frontend

```bash
cd web
npm install
npm run dev
```

Set `REGISTRY_DB_PATH` to an absolute DB path (or use `web/.env.local`).
To enable the homepage manual ingest/scrape button, set
`ENABLE_MANUAL_RUNBOOK_TRIGGER=true` and configure
`RUNBOOK_MANUAL_COMMAND` (plus optional `RUNBOOK_MANUAL_WORKDIR`).

## Test strategy (canonical commands)

Use these commands as the project default in local dev and CI:

### Python

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### Web

```bash
cd web
npm test
npm run typecheck
npm run lint
```

`pytest` is not required for this repository; Python tests are authored and run
with `unittest`.
