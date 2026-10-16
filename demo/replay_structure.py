"""Offline replay of the structure step for already-stored receipts.

Reads raw_markdown from the production DB, re-runs the structure step
against the configured text LLM (no image/OCR), and prints the resulting
discount fields + the arithmetic tool's verdict. Useful for validating
prompt/schema changes against real receipts without re-uploading photos.

Usage (inside the pipeline container, repo mounted at /demo; PH_PROD_DB_DSN
from .env passed in via -e):
    python /demo/replay_structure.py 19 20
"""
import json
import os
import sys

import psycopg
from psycopg.rows import dict_row

from phunter.artifacts import RunArtifacts
from phunter.config import load_config
from phunter.llm import LLMClient
from phunter.steps.structure import _validate_candidate, run_structure

DSN = os.environ.get("PH_PROD_DB_DSN") or sys.exit("set PH_PROD_DB_DSN (see .env)")

cfg = load_config()
client = LLMClient(cfg.text)

with psycopg.connect(DSN, row_factory=dict_row) as conn:
    for rid in map(int, sys.argv[1:]):
        row = conn.execute(
            "SELECT raw_markdown FROM receipts WHERE id = %s", (rid,)
        ).fetchone()
        state = {"ocr": {"text": row["raw_markdown"], "codes": []}}
        slog = RunArtifacts("/tmp/replay", f"replay-{rid}").step(1, "structure")
        out = run_structure(state, cfg.text, client, slog)["structured"]
        print(f"=== receipt {rid} ===")
        print(json.dumps(
            {k: out.get(k) for k in ("subtotal", "discount_total", "total")},
            ensure_ascii=False,
        ))
        print("item discounts:", [it.get("discount") for it in out["items"]])
        print("arith check:", _validate_candidate(json.dumps(out, ensure_ascii=False)))
