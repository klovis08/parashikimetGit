# Registry pipeline — operations runbook

Python entrypoint: `run_registry_pipeline.py` at repo root. It runs, in order:

1. `ingest_registry.py --mode daily` (scraper retries unchanged inside the scraper)
2. `export_registry.py export` (retries on SQLite “database is locked”)
3. `export_registry.py validate --json` (same lock retries; optional via `--skip-validate`)

Failure is **non-zero exit** from the stage that failed; `ingest_registry.py` also exits `1` when the run finishes with `status != "ok"` (e.g. pagination error). Partial success is not treated as overall success.

---

## First-time bootstrap (VPS)

1. **System packages** (Debian/Ubuntu example): `python3`, `python3-venv`, `sqlite3`, `logrotate`, `git`, `ca-certificates`.

2. **Deploy code** (paths are examples; adjust):

   ```bash
   sudo mkdir -p /opt/parashikimet
   sudo chown "$USER:$USER" /opt/parashikimet
   git clone <your-repo> /opt/parashikimet
   cd /opt/parashikimet
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ```

3. **Data directories** and user:

   ```bash
   sudo useradd --system --home /var/lib/parashikimet --shell /usr/sbin/nologin registry || true
   sudo mkdir -p /var/lib/parashikimet/export /var/log/parashikimet
   sudo chown -R registry:registry /var/lib/parashikimet /var/log/parashikimet
   ```

4. **Timezone (Europe/Tirane)** — used for daily “today/yesterday” in `ingest_registry` and for `OnCalendar` interpretation in systemd:

   ```bash
   sudo timedatectl set-timezone Europe/Tirane
   timedatectl
   ```

5. **Bootstrap DB** (full year once):

   ```bash
   sudo -u registry bash -c 'cd /opt/parashikimet && ./venv/bin/python ingest_registry.py \
     --mode bootstrap --db /var/lib/parashikimet/registry.db --year 2026'
   ```

6. **Smoke export + validate**:

   ```bash
  sudo -u registry bash -c 'cd /opt/parashikimet && ./venv/bin/python export_registry.py export \
    --db /var/lib/parashikimet/registry.db --year 2026 --out-dir /var/lib/parashikimet/export'
   sudo -u registry bash -c 'cd /opt/parashikimet && ./venv/bin/python export_registry.py validate \
     --db /var/lib/parashikimet/registry.db --json'
   ```

---

## Daily automation (recommended: systemd timer)

**Why systemd (not cron) here:** dependency units (`network-online`), journal integration, clear `OnCalendar` scheduling, and built-in timer state (`systemctl list-timers`). Cron is still fine; see below.

1. Copy unit files from `ops/systemd/` and adjust `User`/`Group`/`paths` if needed:

   ```bash
   sudo cp /opt/parashikimet/ops/systemd/registry-pipeline-daily.service /etc/systemd/system/
   sudo cp /opt/parashikimet/ops/systemd/registry-pipeline-daily.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now registry-pipeline-daily.timer
   sudo systemctl list-timers --all | grep registry-pipeline
   ```

2. **Log file** (from `ExecStart` `--log-file`): ensure the `registry` user can append:

   ```bash
   sudo touch /var/log/parashikimet/pipeline.log
   sudo chown registry:registry /var/log/parashikimet/pipeline.log
   ```

3. **Log rotation** — copy `ops/logrotate-parashikimet` to `/etc/logrotate.d/parashikimet` and test:

   ```bash
   sudo cp /opt/parashikimet/ops/logrotate-parashikimet /etc/logrotate.d/parashikimet
   sudo logrotate -d /etc/logrotate.d/parashikimet
   ```

---

## Cron alternative (Europe/Tirane)

If the system timezone is `Europe/Tirane`, local crontab times are Tirane wall time:

```cron
15 6 * * * registry cd /opt/parashikimet && /opt/parashikimet/venv/bin/python run_registry_pipeline.py --workdir /opt/parashikimet --db /var/lib/parashikimet/registry.db --out-dir /var/lib/parashikimet/export --log-file /var/log/parashikimet/pipeline.log >>/var/log/parashikimet/pipeline.cron.log 2>&1
```

Prefer redirecting stderr/stdout to a file or journal if you do not use `--log-file`.

---

## Manual re-run

Full pipeline (same as automation):

```bash
cd /opt/parashikimet
./venv/bin/python run_registry_pipeline.py \
  --workdir /opt/parashikimet \
  --db /var/lib/parashikimet/registry.db \
  --out-dir /var/lib/parashikimet/export \
  --log-file /var/log/parashikimet/pipeline.log
```

Single steps (unchanged CLIs):

```bash
./venv/bin/python ingest_registry.py --mode daily --db /var/lib/parashikimet/registry.db --year 2026
./venv/bin/python export_registry.py export --db /var/lib/parashikimet/registry.db --year 2026 --out-dir /var/lib/parashikimet/export
./venv/bin/python export_registry.py validate --db /var/lib/parashikimet/registry.db --json
```

---

## Inspect latest run status

- **Systemd:** `journalctl -u registry-pipeline-daily.service -n 200 --no-pager`
- **Log file:** `tail -n 200 /var/log/parashikimet/pipeline.log`
- **Grep metrics:** `grep METRICS /var/log/parashikimet/pipeline.log | tail`
- **Last exit code (systemd):** `systemctl show -p Result registry-pipeline-daily.service` after a run (oneshot; see journal for details)

Structured **JSON lines** (if you pass `--log-format jsonl`): lines containing `METRICS_JSON`.

---

## Failure scenarios

| Symptom | What to check | Recovery |
|--------|----------------|----------|
| Network / site down | `ingest` errors in log; HTTP in stderr | Wait; re-run pipeline; ingest has internal request retries; orchestrator retries daily ingest (`--ingest-attempts`) |
| `database is locked` | Export/validate log lines about lock | Re-run; exporter retries with backoff; avoid concurrent writers on same DB path |
| Ingest `status != "ok"` | JSON `error_message` / `stopped_reason` | Fix underlying issue; re-run; DB may still be consistent for export of previous data |
| Validate exit 1 | Sanity cases failed | Fix classifier / data; see `export_registry.py validate` output |
| Validate exit 2 | Invariant violations | Investigate rows; see validate JSON |
| Partial run (ingest ok, export failed) | Non-zero exit from `export` | Fix disk/permissions; re-run from `export` step manually if ingest already completed |

---

## Alerting (optional)

- **`REGISTRY_PIPELINE_ALERT_URL`:** HTTP POST JSON on failure: `{ "run_id", "stage", "message", "details" }`.
- **`REGISTRY_PIPELINE_ALERT_CMD`:** Executable path; JSON on stdin (see `ops/alert_notify.example.sh`).

If neither is set, failures are visible only via exit code and logs (documented extension point).

---

## Assumptions and risks

- **Single writer** on `registry.db` at a time; concurrent runs can lock SQLite.
- **Disk space** for CSV exports and logs is not monitored here.
- **Secret URLs** in environment: protect service unit permissions (`chmod 640` on drop-ins with tokens).
- **Bootstrap** is large; run off-peak and monitor duration.
