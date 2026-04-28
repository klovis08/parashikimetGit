# Deployment (VPS)

## Configuration

- `REGISTRY_DB_PATH`: recommended absolute path to the SQLite file produced by `ingest_registry.py`.
  - If unset, the API checks `../registry.db` then `./registry.db` relative to the app working directory.
- `PORT`: HTTP port (Next.js reads this at runtime; default `3000`).
- Optional: copy `.env.example` to `.env` in `web/` or export variables in the systemd unit.

## Install and build

```bash
cd web
npm ci
npm run build
```

Node.js 20+ recommended (LTS).

## Start (foreground)

```bash
cd /path/to/parashikimet/web
export REGISTRY_DB_PATH=/path/to/registry.db
export PORT=3000
npm run start
```

## Reverse proxy (optional)

Point Nginx (or Caddy) at `http://127.0.0.1:3000`. Example Nginx snippet:

```nginx
location / {
  proxy_pass http://127.0.0.1:3000;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
}
```

## systemd service

`/etc/systemd/system/parashikimet-web.service`:

```ini
[Unit]
Description=Parashikimet Next.js web
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/parashikimet/web
Environment=NODE_ENV=production
Environment=REGISTRY_DB_PATH=/path/to/registry.db
Environment=PORT=3000
ExecStart=/usr/bin/npm run start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then: `sudo systemctl daemon-reload && sudo systemctl enable --now parashikimet-web.service`

Ensure the service user can read `REGISTRY_DB_PATH` (and the directory). After nightly ingest, the same file is updated in place; Next.js opens the DB per request via better-sqlite3, so new rows are visible without restarting (SQLite read concurrency is fine for this MVP).

## Software filter (tradeoff)

When `software=broad` or `strict`, the API streams SQL-matching rows and classifies per row with the same rules as `registry_classifier.py`, so memory usage stays bounded to page size. For very large tables this still has CPU cost because classification remains runtime/evaluated per row; consider persisted `software_broad` / `software_strict` columns updated in the ingest/export pipeline for faster filtering.
