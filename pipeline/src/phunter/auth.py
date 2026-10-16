"""Auth dependency: every endpoint except /check_account must present a
matching X-PAT / X-Device-Id pair."""
from __future__ import annotations

import logging

from fastapi import Header, HTTPException, Request

from .db import ReceiptDB

log = logging.getLogger("phunter.auth")


def _mask(pat: str | None) -> str:
    return f"{pat[:6]}…" if pat else "<none>"


def require_account(
    request: Request,
    x_pat: str | None = Header(default=None),
    x_device_id: str | None = Header(default=None),
) -> int:
    db: ReceiptDB = request.app.state.db
    account_id = db.authenticate(x_pat, x_device_id)
    if account_id is None:
        log.warning(
            "auth REJECTED: %s %s device=%s (no matching PAT/device pair)",
            request.method,
            request.url.path,
            x_device_id or "<none>",
        )
        raise HTTPException(401, detail="missing or mismatched X-PAT / X-Device-Id pair")
    return account_id
