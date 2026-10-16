"""Postgres persistence (psycopg v3): receipts, accounts, devices, requests."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("phunter.db")


class ReceiptDB:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _conn(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    # ---- receipts -----------------------------------------------------------

    def insert_receipt(
        self,
        run_id: str,
        image_path: str,
        structured: dict[str, Any],
        raw_markdown: str,
        ocr_json: dict[str, Any],
        request_id: int | None = None,
        sum_verified: bool | None = None,
    ) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO receipts (run_id, image_path, store_name, receipt_date,
                                      total, discount_total, sum_verified, raw_markdown,
                                      ocr_json, structured_json, request_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                -- re-processing a request (manual re-queue of a completed
                -- one) reuses run_id: replace the receipt in place instead
                -- of tripping the run_id UNIQUE constraint
                ON CONFLICT (run_id) DO UPDATE SET
                    image_path = EXCLUDED.image_path,
                    store_name = EXCLUDED.store_name,
                    receipt_date = EXCLUDED.receipt_date,
                    total = EXCLUDED.total,
                    discount_total = EXCLUDED.discount_total,
                    sum_verified = EXCLUDED.sum_verified,
                    raw_markdown = EXCLUDED.raw_markdown,
                    ocr_json = EXCLUDED.ocr_json,
                    structured_json = EXCLUDED.structured_json,
                    request_id = EXCLUDED.request_id
                RETURNING id
                """,
                (
                    run_id,
                    image_path,
                    structured.get("store_name"),
                    structured.get("date"),
                    structured.get("total"),
                    structured.get("discount_total"),
                    sum_verified,
                    raw_markdown,
                    json.dumps(ocr_json, ensure_ascii=False),
                    json.dumps(structured, ensure_ascii=False),
                    request_id,
                ),
            )
            receipt_id = cur.fetchone()["id"]

            # on re-processing, drop the previous line rows first
            cur.execute("DELETE FROM receipt_items WHERE receipt_id = %s", (receipt_id,))
            for pos, item in enumerate(structured.get("items", []), start=1):
                cur.execute(
                    """
                    INSERT INTO receipt_items (receipt_id, position, name, qty, unit,
                                               price, sum, discount, tax)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        receipt_id,
                        pos,
                        item.get("name"),
                        item.get("qty"),
                        item.get("unit"),
                        item.get("price"),
                        item.get("sum"),
                        item.get("discount"),
                        item.get("tax"),
                    ),
                )
            conn.commit()
        return receipt_id

    def get_receipt(self, receipt_id: int, account_id: int) -> dict[str, Any] | None:
        """Receipt header + items, scoped to the owning account via its request."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.* FROM receipts r
                LEFT JOIN requests q ON q.id = r.request_id
                WHERE r.id = %s AND (q.account_id = %s OR r.request_id IS NULL)
                """,
                (receipt_id, account_id),
            )
            header = cur.fetchone()
            if header is None:
                return None
            cur.execute(
                "SELECT position, name, qty, unit, price, sum, discount, tax FROM receipt_items "
                "WHERE receipt_id = %s ORDER BY position",
                (receipt_id,),
            )
            header["items"] = [dict(r) for r in cur.fetchall()]
            for col in ("created_at",):
                if header.get(col) is not None:
                    header[col] = header[col].isoformat()
            return header

    # ---- migrations -----------------------------------------------------------

    def apply_migrations(self, init_dir: str) -> list[str]:
        """Apply db/init/*.sql in filename order, tracking applied files in
        schema_migrations. Safe on fresh and existing volumes; all files are
        idempotent anyway."""
        applied: list[str] = []
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "  filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            cur.execute("SELECT filename FROM schema_migrations")
            done = {r["filename"] for r in cur.fetchall()}
            for f in sorted(Path(init_dir).glob("*.sql")):
                if f.name in done:
                    log.debug("migration already applied: %s", f.name)
                    continue
                log.info("applying migration: %s", f.name)
                cur.execute(f.read_text())
                cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,))
                applied.append(f.name)
            conn.commit()
        if applied:
            log.info("migrations applied: %s; schema_migrations now: %s",
                     applied, sorted(done | set(applied)))
        return applied

    def ping(self) -> bool:
        with psycopg.connect(self.dsn) as conn:
            conn.execute("SELECT 1")
        return True

    # ---- accounts / devices ---------------------------------------------------

    def check_account(self, device_id: str, pat: str | None) -> dict[str, Any]:
        """Bootstrap per spec: device-first, then pat, then create everything.

        Deliberate security debt (per user): a known device always gets its
        stored pat back, even when the input pat mismatches.
        """
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT d.device_id, d.account_id, a.pat "
                "FROM devices d JOIN accounts a ON a.id = d.account_id "
                "WHERE d.device_id = %s",
                (device_id,),
            )
            row = cur.fetchone()
            if row:
                conn.commit()
                return {"pat": row["pat"], "account_id": row["account_id"],
                        "is_new": False, "branch": "device_found"}

            if pat:
                cur.execute("SELECT id, pat FROM accounts WHERE pat = %s", (pat,))
                account = cur.fetchone()
                if account:
                    cur.execute(
                        "INSERT INTO devices (device_id, account_id) VALUES (%s, %s)",
                        (device_id, account["id"]),
                    )
                    conn.commit()
                    return {"pat": account["pat"], "account_id": account["id"],
                            "is_new": False, "branch": "device_paired_by_pat"}

            new_pat = uuid.uuid4().hex
            cur.execute("INSERT INTO accounts (pat) VALUES (%s) RETURNING id", (new_pat,))
            account_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO devices (device_id, account_id) VALUES (%s, %s)",
                (device_id, account_id),
            )
            conn.commit()
            return {"pat": new_pat, "account_id": account_id,
                    "is_new": True, "branch": "new_account"}

    def authenticate(self, pat: str | None, device_id: str | None) -> int | None:
        """Strict pair check: the device must belong to the pat's account."""
        if not pat or not device_id:
            return None
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT a.id FROM accounts a "
                "JOIN devices d ON d.account_id = a.id "
                "WHERE a.pat = %s AND d.device_id = %s",
                (pat, device_id),
            )
            row = cur.fetchone()
            return row["id"] if row else None

    # ---- requests -------------------------------------------------------------

    def create_request(self, account_id: int, device_id: str | None, artifacts_dir: str) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO requests (account_id, device_id, artifacts_dir) "
                "VALUES (%s, %s, %s) RETURNING id",
                (account_id, device_id, artifacts_dir),
            )
            rid = cur.fetchone()["id"]
            conn.commit()
        return rid

    def recover_interrupted(self) -> list[int]:
        """Re-queue requests left in 'running' by a previous process
        (server restart / crash mid-pipeline). Returns recovered ids."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE requests SET status = 'queued', stage = NULL, "
                "started_at = NULL, status_at = now() "
                "WHERE status = 'running' RETURNING id"
            )
            ids = [r["id"] for r in cur.fetchall()]
            conn.commit()
        return ids

    def requeue_failed(self, max_retries: int) -> dict[str, Any] | None:
        """Queue-drain recovery: requeue the failed request that has waited
        longest (oldest status_at), up to `max_retries` attempts."""
        if max_retries <= 0:
            return None
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                WITH nxt AS (
                    SELECT id FROM requests
                    WHERE status = 'failed' AND retry_count < %s
                    ORDER BY status_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE requests r
                SET status = 'queued', stage = NULL, started_at = NULL,
                    status_at = now(), retry_count = retry_count + 1
                FROM nxt WHERE r.id = nxt.id
                RETURNING r.*
                """,
                (max_retries,),
            )
            row = cur.fetchone()
            conn.commit()
        return dict(row) if row else None

    def claim_next_queued(self) -> dict[str, Any] | None:
        """Atomically take the oldest queued request (single worker, but the
        SKIP LOCKED keeps this safe if the process ever runs >1 thread)."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                WITH nxt AS (
                    SELECT id FROM requests WHERE status = 'queued'
                    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE requests r
                SET status = 'running', started_at = now(), status_at = now()
                FROM nxt WHERE r.id = nxt.id
                RETURNING r.*
                """
            )
            row = cur.fetchone()
            conn.commit()
        return dict(row) if row else None

    def set_request_stage(self, request_id: int, stage: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE requests SET stage = %s, status_at = now() WHERE id = %s",
                (stage, request_id),
            )
            conn.commit()

    def finish_request(self, request_id: int, status: str, error: str | None = None,
                       exhaust_retries: int | None = None) -> None:
        """exhaust_retries: set retry_count to that value so requeue_failed
        (which requires retry_count < max) skips this request permanently."""
        with self._conn() as conn:
            if exhaust_retries is None:
                conn.execute(
                    "UPDATE requests SET status = %s, status_at = now(), finished_at = now(), "
                    "error = %s WHERE id = %s",
                    (status, error, request_id),
                )
            else:
                conn.execute(
                    "UPDATE requests SET status = %s, status_at = now(), finished_at = now(), "
                    "error = %s, retry_count = %s WHERE id = %s",
                    (status, error, exhaust_retries, request_id),
                )
            conn.commit()

    def get_request(self, request_id: int, account_id: int) -> dict[str, Any] | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT q.id, q.status, q.stage, q.created_at, q.status_at, q.started_at,
                       q.finished_at, q.error,
                       (SELECT r.id FROM receipts r WHERE r.request_id = q.id) AS receipt_id
                FROM requests q WHERE q.id = %s AND q.account_id = %s
                """,
                (request_id, account_id),
            )
            row = cur.fetchone()
        return self._request_view(dict(row)) if row else None

    def list_requests(self, account_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT q.id, q.status, q.stage, q.created_at, q.status_at, q.started_at,
                       q.finished_at, q.error,
                       (SELECT r.id FROM receipts r WHERE r.request_id = q.id) AS receipt_id,
                       (SELECT r.store_name FROM receipts r WHERE r.request_id = q.id) AS store_name,
                       (SELECT r.total FROM receipts r WHERE r.request_id = q.id) AS total
                FROM requests q WHERE q.account_id = %s
                ORDER BY q.id DESC LIMIT %s
                """,
                (account_id, limit),
            )
            rows = [self._request_view(dict(r)) for r in cur.fetchall()]
        return rows

    @staticmethod
    def _request_view(row: dict[str, Any]) -> dict[str, Any]:
        for col in ("created_at", "status_at", "started_at", "finished_at"):
            if row.get(col) is not None:
                row[col] = row[col].isoformat()
        # duration from start: while running -> now - started_at (client can
        # also compute; server value keeps clocks consistent)
        if row.get("started_at") and not row.get("finished_at"):
            started = datetime.fromisoformat(row["started_at"])
            row["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        elif row.get("started_at") and row.get("finished_at"):
            started = datetime.fromisoformat(row["started_at"])
            finished = datetime.fromisoformat(row["finished_at"])
            row["duration_s"] = round((finished - started).total_seconds(), 1)
        else:
            row["duration_s"] = None
        return row
