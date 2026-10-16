"""Step 4: write the structured receipt to Postgres."""
from __future__ import annotations

from ..artifacts import StepLog
from ..db import ReceiptDB
from ..verify import verify_receipt


def run_persist(state: dict, db: ReceiptDB, slog: StepLog) -> dict:
    slog.write_input(f"# persist\n\ndsn: {db.dsn.split('@')[-1]}\n")

    verified = verify_receipt(state["structured"])
    receipt_id = db.insert_receipt(
        run_id=state["run_id"],
        image_path=state["resized_path"],
        structured=state["structured"],
        raw_markdown=state["ocr"]["text"],
        ocr_json=state["ocr"],
        request_id=state.get("request_id"),
        sum_verified=verified,
    )

    out = {
        "receipt_id": receipt_id,
        "items": len(state["structured"].get("items", [])),
        "sum_verified": verified,
    }
    slog.write_output(out)
    return {"receipt_id": receipt_id}
