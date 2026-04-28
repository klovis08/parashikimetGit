#!/usr/bin/env python3
"""
Production orchestration: daily ingest -> CSV export -> validate.

Designed for cron/systemd on Linux VPS. Logs are timestamped, grep-friendly,
with optional JSON lines. Non-zero exit if any stage fails or ingest status != ok.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Repo root: directory containing this script (run from there or set --workdir)
REPO_ROOT = Path(__file__).resolve().parent


@dataclass
class StageMetrics:
    """Aggregated for the final run summary line / JSONL record."""

    run_id: str
    started_at: str
    finished_at: str
    status: str
    failure_stage: str | None
    pages_visited: int | None = None
    rows_parsed: int | None = None
    rows_inserted: int | None = None
    duplicates_skipped: int | None = None
    failures_retries: int | None = None
    export_full: int | None = None
    export_software_broad: int | None = None
    export_software_strict: int | None = None
    validate_total_full: int | None = None
    validate_broad: int | None = None
    validate_strict: int | None = None
    validate_invariant_violations: int | None = None
    feedback_labels_total: int | None = None
    feedback_labels_used: int | None = None
    exit_code: int = 0
    error_message: str | None = None
    alert_sent: bool = False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("empty output from subprocess")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}\s*$", text)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"could not parse JSON from output: {text[:500]!r}")


def _run_subprocess(
    argv: list[str],
    logger: logging.Logger,
    stage: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    line = " ".join(shlex_quote_if_needed(a) for a in argv)
    logger.info("[%s] CMD %s", stage, line)
    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )


def shlex_quote_if_needed(s: str) -> str:
    if re.match(r"^[\w./:@+-]+$", s):
        return s
    from shlex import quote

    return quote(s)


def _run_with_sqlite_lock_retries(
    argv: list[str],
    logger: logging.Logger,
    stage: str,
    cwd: Path,
    max_attempts: int,
    base_delay_sec: float,
) -> subprocess.CompletedProcess[str]:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(max_attempts):
        last = _run_subprocess(argv, logger, stage, cwd=cwd)
        if last.returncode == 0:
            return last
        combined = (last.stderr or "") + (last.stdout or "")
        if "database is locked" in combined.lower() and attempt < max_attempts - 1:
            delay = base_delay_sec * (2**attempt)
            logger.warning(
                "[%s] SQLite locked; retry %s/%s in %.1fs",
                stage,
                attempt + 1,
                max_attempts,
                delay,
            )
            time.sleep(delay)
            continue
        return last
    assert last is not None
    return last


def _log_jsonl(logger: logging.Logger, log_format: str, payload: dict[str, Any]) -> None:
    if log_format == "jsonl":
        logger.info("METRICS_JSON %s", json.dumps(payload, ensure_ascii=False))
    else:
        parts = [f"{k}={v}" for k, v in payload.items() if v is not None]
        logger.info("METRICS " + " ".join(parts))


def _post_webhook(url: str, body: dict[str, Any], timeout: float = 15.0) -> None:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "run_registry_pipeline/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def _run_alert_hook(
    run_id: str,
    stage: str,
    message: str,
    details: dict[str, Any],
    logger: logging.Logger,
) -> bool:
    """Returns True if a notification was sent or hook ran."""
    url = (os.environ.get("REGISTRY_PIPELINE_ALERT_URL") or "").strip()
    hook = (os.environ.get("REGISTRY_PIPELINE_ALERT_CMD") or "").strip()
    if url:
        try:
            _post_webhook(
                url,
                {
                    "run_id": run_id,
                    "stage": stage,
                    "message": message,
                    "details": details,
                },
            )
            logger.info("[alert] POST %s (truncated) ok", url[:48])
            return True
        except (urllib.error.URLError, OSError) as e:
            logger.error("[alert] webhook failed: %s", e)
    if hook:
        try:
            payload = json.dumps(
                {
                    "run_id": run_id,
                    "stage": stage,
                    "message": message,
                    "details": details,
                }
            )
            subprocess.run(
                [hook],
                input=payload,
                text=True,
                timeout=60,
                check=False,
                shell=False,
            )
            return True
        except OSError as e:
            logger.error("[alert] hook failed: %s", e)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run daily ingest, export, and optional validation in sequence."
    )
    ap.add_argument(
        "--workdir",
        type=Path,
        default=REPO_ROOT,
        help="Process cwd for subprocesses (default: script directory / repo root)",
    )
    ap.add_argument("--db", default="registry.db", help="SQLite path (passed to ingest/export)")
    ap.add_argument(
        "--out-dir",
        default=".",
        help="CSV output directory (passed to export_registry export)",
    )
    ap.add_argument("--year", default="2026", help="Ingest year filter (viti)")
    ap.add_argument("--python", default=sys.executable, help="Python to run scripts")
    ap.add_argument(
        "--skip-validate",
        action="store_true",
        help="Do not run export_registry validate",
    )
    ap.add_argument(
        "--feedback-report-json",
        default="",
        help="Optional output path for feedback_loop.py report JSON artifact",
    )
    ap.add_argument(
        "--feedback-report-csv",
        default="",
        help="Optional output path for feedback_loop.py report CSV artifact",
    )
    ap.add_argument(
        "--ingest-attempts",
        type=int,
        default=3,
        help="Max ingest attempts (orchestrator-level, e.g. transient network)",
    )
    ap.add_argument(
        "--ingest-retry-delay",
        type=float,
        default=60.0,
        help="Base seconds between failed ingest attempts (exponential)",
    )
    ap.add_argument(
        "--lock-retries",
        type=int,
        default=4,
        help="Export/validate retries on 'database is locked' (sequential steps)",
    )
    ap.add_argument(
        "--lock-retry-delay",
        type=float,
        default=2.0,
        help="Base delay for lock retries (seconds, exponential)",
    )
    ap.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Append logs here (in addition to stderr)",
    )
    ap.add_argument(
        "--log-format",
        choices=("text", "jsonl"),
        default="text",
        help="METRICS line: text (k=v) or jsonl (METRICS_JSON {…})",
    )
    args = ap.parse_args()

    ingest_attempts = max(1, args.ingest_attempts)
    lock_retries = max(1, args.lock_retries)

    workdir = args.workdir.resolve()

    run_id = os.environ.get("REGISTRY_PIPELINE_RUN_ID") or _utc_now_iso().replace(":", "")
    start_ts = _utc_now_iso()

    log = logging.getLogger("registry_pipeline")
    log.setLevel(logging.INFO)
    fmt = "[%(asctime)s] [%(name)s] %(levelname)s %(message)s"
    # ISO-like times in local TZ for readability on VPS
    datefmt = "%Y-%m-%dT%H:%M:%S"
    root_fmt = logging.Formatter(fmt, datefmt=datefmt)
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(root_fmt)
    log.handlers.clear()
    log.addHandler(h)
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(args.log_file, encoding="utf-8")
        fh.setFormatter(root_fmt)
        log.addHandler(fh)

    def notice(stage: str, msg: str, **extra: Any) -> None:
        if extra:
            log.info("[%s] %s | %s", stage, msg, " ".join(f"{k}={v}" for k, v in extra.items()))
        else:
            log.info("[%s] %s", stage, msg)

    m = StageMetrics(
        run_id=run_id,
        started_at=start_ts,
        finished_at="",
        status="ok",
        failure_stage=None,
    )

    def fail(stage: str, code: int, err: str) -> int:
        m.status = "error"
        m.failure_stage = stage
        m.exit_code = code
        m.error_message = err
        m.finished_at = _utc_now_iso()
        notice(stage, f"FAIL {err}", exit=code)
        m.alert_sent = _run_alert_hook(
            run_id, stage, err, {**asdict(m), "workdir": str(workdir)}, log
        )
        _log_jsonl(log, args.log_format, asdict(m))
        return code

    notice("start", f"run_id={run_id} workdir={workdir}")

    ingest_args = [
        str(Path(args.python).resolve()) if args.python else sys.executable,
        str(workdir / "ingest_registry.py"),
        "--mode",
        "daily",
        "--db",
        str(args.db),
        "--year",
        str(args.year),
    ]

    env = os.environ.copy()
    # Stable locale for logs
    env.setdefault("PYTHONUTF8", "1")

    last_exc: str | None = None
    for att in range(ingest_attempts):
        notice(
            "ingest",
            f"attempt {att + 1}/{ingest_attempts}",
        )
        cp = _run_subprocess(ingest_args, log, "ingest", cwd=workdir, env=env)
        if cp.returncode == 0:
            try:
                summary = _parse_json_object(cp.stdout or "")
            except ValueError as e:
                return fail("ingest", 3, f"parse ingest output: {e}; stdout={cp.stdout!r}")
            st = str(summary.get("status") or "")
            m.pages_visited = int(summary.get("pages_visited") or 0)
            m.rows_parsed = int(summary.get("rows_parsed") or 0)
            m.rows_inserted = int(summary.get("rows_inserted") or 0)
            m.duplicates_skipped = int(summary.get("duplicates_skipped") or 0)
            m.failures_retries = int(summary.get("failures_retries") or 0)
            if st != "ok":
                return fail("ingest", 4, f"ingest status={st!r} {summary.get('error_message', '')!s}")
            notice(
                "ingest",
                "ok",
                pages=m.pages_visited,
                rows_parsed=m.rows_parsed,
                inserted=m.rows_inserted,
                dup_skip=m.duplicates_skipped,
                retries=m.failures_retries,
            )
            _log_jsonl(
                log,
                args.log_format,
                {
                    "ts": _utc_now_iso(),
                    "run_id": run_id,
                    "stage": "ingest",
                    "event": "end",
                    "status": "ok",
                    "pages_visited": m.pages_visited,
                    "rows_parsed": m.rows_parsed,
                    "rows_inserted": m.rows_inserted,
                    "duplicates_skipped": m.duplicates_skipped,
                    "failures_retries": m.failures_retries,
                },
            )
            break
        last_exc = (cp.stderr or cp.stdout or "").strip() or f"exit {cp.returncode}"
        if att < ingest_attempts - 1:
            delay = args.ingest_retry_delay * (2**att)
            notice("ingest", f"non-zero exit, retrying in {delay:.0f}s", detail=last_exc[:300])
            time.sleep(delay)
    else:
        return fail("ingest", 2, f"ingest failed after {ingest_attempts} attempts: {last_exc}")

    export_argv = [
        str(Path(args.python).resolve()) if args.python else sys.executable,
        str(workdir / "export_registry.py"),
        "export",
        "--db",
        str(args.db),
        "--year",
        str(args.year),
        "--out-dir",
        str(args.out_dir),
    ]
    ex = _run_with_sqlite_lock_retries(
        export_argv,
        log,
        "export",
        workdir,
        max_attempts=lock_retries,
        base_delay_sec=args.lock_retry_delay,
    )
    if ex.returncode != 0:
        return fail("export", 5, f"export stderr={ex.stderr!r} stdout={ex.stdout!r}")
    try:
        ex_summary = _parse_json_object(ex.stdout or "")
    except ValueError as e:
        return fail("export", 6, f"parse export: {e}")
    m.export_full = int(ex_summary.get("full", 0))
    m.export_software_broad = int(ex_summary.get("software_broad", 0))
    m.export_software_strict = int(ex_summary.get("software_strict", 0))
    notice(
        "export",
        "ok",
        full=m.export_full,
        software_broad=m.export_software_broad,
        software_strict=m.export_software_strict,
    )
    _log_jsonl(
        log,
        args.log_format,
        {
            "ts": _utc_now_iso(),
            "run_id": run_id,
            "stage": "export",
            "event": "end",
            "status": "ok",
            "export_full": m.export_full,
            "export_software_broad": m.export_software_broad,
            "export_software_strict": m.export_software_strict,
        },
    )

    if not args.skip_validate:
        val_argv = [
            str(Path(args.python).resolve()) if args.python else sys.executable,
            str(workdir / "export_registry.py"),
            "validate",
            "--db",
            str(args.db),
            "--json",
        ]
        val = _run_with_sqlite_lock_retries(
            val_argv,
            log,
            "validate",
            workdir,
            max_attempts=lock_retries,
            base_delay_sec=args.lock_retry_delay,
        )
        if val.returncode != 0:
            return fail(
                "validate",
                val.returncode,
                f"validate failed rc={val.returncode} out={val.stdout!r} err={val.stderr!r}",
            )
        try:
            val_out = _parse_json_object(val.stdout or "")
        except ValueError as e:
            return fail("validate", 7, f"parse validate: {e}")
        m.validate_total_full = int(val_out.get("total_full_rows", 0))
        m.validate_broad = int(val_out.get("broad_rows", 0))
        m.validate_strict = int(val_out.get("strict_rows", 0))
        m.validate_invariant_violations = int(
            val_out.get("classification_invariant_violations", 0)
        )
        if not val_out.get("all_ok", True):
            return fail("validate", 1, "hardware_repair_sanity_cases not all ok")
        notice(
            "validate",
            "ok",
            total=m.validate_total_full,
            broad=m.validate_broad,
            strict=m.validate_strict,
            inv_viol=m.validate_invariant_violations,
        )
        _log_jsonl(
            log,
            args.log_format,
            {
                "ts": _utc_now_iso(),
                "run_id": run_id,
                "stage": "validate",
                "event": "end",
                "status": "ok",
                "total_full_rows": m.validate_total_full,
                "broad_rows": m.validate_broad,
                "strict_rows": m.validate_strict,
                "classification_invariant_violations": m.validate_invariant_violations,
            },
        )

    if args.feedback_report_json or args.feedback_report_csv:
        fb_argv = [
            str(Path(args.python).resolve()) if args.python else sys.executable,
            str(workdir / "feedback_loop.py"),
            "report",
            "--db",
            str(args.db),
        ]
        if args.feedback_report_json:
            fb_argv.extend(["--out-json", str(args.feedback_report_json)])
        if args.feedback_report_csv:
            fb_argv.extend(["--out-csv", str(args.feedback_report_csv)])
        fb = _run_with_sqlite_lock_retries(
            fb_argv,
            log,
            "feedback_report",
            workdir,
            max_attempts=lock_retries,
            base_delay_sec=args.lock_retry_delay,
        )
        if fb.returncode != 0:
            return fail(
                "feedback_report",
                fb.returncode,
                f"feedback report failed rc={fb.returncode} out={fb.stdout!r} err={fb.stderr!r}",
            )
        try:
            fb_out = _parse_json_object(fb.stdout or "")
        except ValueError as e:
            return fail("feedback_report", 8, f"parse feedback report: {e}")
        m.feedback_labels_total = int(fb_out.get("labels_total", 0))
        m.feedback_labels_used = int(fb_out.get("labels_used_for_metrics", 0))
        notice(
            "feedback_report",
            "ok",
            labels_total=m.feedback_labels_total,
            labels_used=m.feedback_labels_used,
        )

    m.finished_at = _utc_now_iso()
    m.status = "ok"
    notice("done", "all stages completed")
    _log_jsonl(
        log,
        args.log_format,
        {k: v for k, v in asdict(m).items() if v is not None},
    )
    return 0


if __name__ == "__main__":
    try:
        code = int(main() or 0)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        code = 130
    raise SystemExit(code)
