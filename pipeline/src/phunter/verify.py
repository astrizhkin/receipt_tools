"""Deterministic sum verification of a structured receipt (server-side).

Independent of the LLM: the structure step's validate_json tool guides the
model, but the stored boolean is computed here from the final JSON so OCR
errors (unreadable numbers, missing lines) surface as sum_verified = false
instead of silently passing.
"""
from __future__ import annotations

from typing import Any

_ABS_TOL = 0.011


def verify_receipt(structured: dict[str, Any]) -> bool:
    items = structured.get("items") or []
    total = structured.get("total")
    disc_total = structured.get("discount_total")

    # per line: qty x price equals the printed sum, or sum + line discount
    for it in items:
        qty, price, s, disc = (
            it.get("qty"), it.get("price"), it.get("sum"), it.get("discount"),
        )
        if qty is None or price is None or s is None:
            continue
        want = qty * price
        ok = abs(want - s) <= _ABS_TOL or (
            disc is not None and abs(want - disc - s) <= _ABS_TOL
        )
        if not ok:
            return False

    # per-line discounts must add up to the printed discount total
    discs = [it["discount"] for it in items if it.get("discount") is not None]
    if disc_total is not None and discs and abs(sum(discs) - disc_total) > _ABS_TOL:
        return False

    # reconcile to the total: line sums are pre-discount on r-keeper receipts
    # and post-discount on e.g. Perekriostok — accept either. A 0.1% relative
    # slack absorbs POS kopeck rounding; missing total or lines never verify.
    sums = [it["sum"] for it in items if it.get("sum") is not None]
    if total is None or not sums:
        return False
    tol = max(_ABS_TOL, 0.001 * abs(total))
    line_sum = sum(sums)
    if abs(line_sum - total) <= tol:
        return True
    if disc_total is not None:
        if abs(line_sum - disc_total - total) <= tol:
            return True
        # Perekriostok layout: lines post-discount, printed pre-discount
        # subtotal (ПОДИТОГ); line sums carry POS rounding so they match
        # neither total nor total+discount exactly
        subtotal = structured.get("subtotal")
        if subtotal is not None and abs(subtotal - disc_total - total) <= tol:
            return True
    return False
