"""Backfill receipts.sum_verified using phunter.verify.verify_receipt.

Run inside the pipeline container (repo demo/ mounted at /demo; PH_PROD_DB_DSN
from .env passed in via -e):
    python /demo/backfill_sum_verified.py
Idempotent: recomputes the flag for every row from its structured_json.
"""
import os
import sys

import psycopg
from psycopg.rows import dict_row

from phunter.verify import verify_receipt

DSN = os.environ.get("PH_PROD_DB_DSN") or sys.exit("set PH_PROD_DB_DSN (see .env)")

with psycopg.connect(DSN, row_factory=dict_row) as conn:
    rows = conn.execute(
        """
        SELECT r.id, r.store_name, r.discount_total, r.structured_json,
               coalesce((SELECT jsonb_agg(i.discount ORDER BY i.position)
                         FROM receipt_items i WHERE i.receipt_id = r.id), '[]')
                 AS item_discounts
        FROM receipts r ORDER BY r.id
        """
    ).fetchall()
    for r in rows:
        # older rows carry discounts only in the table columns (backfilled),
        # not inside structured_json — merge them in before verifying
        s = dict(r["structured_json"])
        if s.get("discount_total") is None and r["discount_total"] is not None:
            s["discount_total"] = float(r["discount_total"])
        discs = r["item_discounts"] or []
        for it, d in zip(s.get("items", []), discs):
            if it.get("discount") is None and d is not None:
                it["discount"] = float(d)
        v = verify_receipt(s)
        conn.execute(
            "UPDATE receipts SET sum_verified = %s WHERE id = %s", (v, r["id"])
        )
        print(f"receipt {r['id']:>3}  verified={v}  {r['store_name']!r}")
    conn.commit()
