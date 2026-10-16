"""REST API: account bootstrap, async photo_input, request status, receipts.

Auth: every endpoint except /check_account requires a matching
X-PAT / X-Device-Id header pair (see auth.py).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .artifacts import RunArtifacts
from .auth import require_account
from .config import load_config
from .db import ReceiptDB
from .worker import Worker

log = logging.getLogger("phunter")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

cfg = load_config()
db = ReceiptDB(cfg.db.dsn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_dir = os.environ.get("PH_INIT_DIR", "/docker-entrypoint-initdb.d")
    try:
        applied = db.apply_migrations(init_dir)
        if applied:
            log.info("applied migrations: %s", applied)
        else:
            log.info("migrations up to date (dir=%s)", init_dir)
    except Exception:  # noqa: BLE001 — startup must not die on schema drift
        log.exception("migration run failed (dir=%s)", init_dir)
    worker = Worker(cfg, db)
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="receipt_tools pipeline", version="0.2.0", lifespan=lifespan)
app.state.db = db
app.state.cfg = cfg

# Safety net for browser clients that hit the pipeline directly; the nginx
# web container normally proxies /api/ same-origin so CORS never applies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _looks_like_image(data: bytes) -> bool:
    """Magic-byte sniffing: Android's http MultipartFile sends parts as
    application/octet-stream unless the client sets a content type."""
    return (
        data[:3] == b"\xff\xd8\xff"                       # JPEG
        or data[:8] == b"\x89PNG\r\n\x1a\n"               # PNG
        or data[:4] == b"RIFF" and data[8:12] == b"WEBP"  # WEBP
    )


# ---- in-app updates (unauthenticated: the app checks before login) ---------

RELEASE_DIR = os.path.join(cfg.artifacts_dir, "release")


@app.get("/app_update")
def app_update() -> dict:
    """Version manifest for the self-distributed Android app.
    Written by demo/build_apk.sh into artifacts/release/version.json."""
    manifest = os.path.join(RELEASE_DIR, "version.json")
    if not os.path.exists(manifest):
        raise HTTPException(404, detail="no published app release")
    with open(manifest) as f:
        data = json.load(f)
    # relative so the app resolves it against its own configured server URL
    data["url"] = "/app_update/apk"
    return data


@app.get("/app_update/apk")
def app_update_apk() -> FileResponse:
    apk = os.path.join(RELEASE_DIR, "app-release.apk")
    if not os.path.exists(apk):
        raise HTTPException(404, detail="no published app release")
    return FileResponse(
        apk,
        media_type="application/vnd.android.package-archive",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/health")
def health() -> dict:
    try:
        db_ok = db.ping()
        db_err = None
    except Exception as e:  # noqa: BLE001 — health must not raise
        db_ok, db_err = False, str(e)
    return {"status": "ok", "db": db_ok, "db_error": db_err}


class CheckAccountIn(BaseModel):
    device_id: str
    pat: str | None = None


@app.post("/check_account")
def check_account(body: CheckAccountIn) -> dict:
    if not body.device_id.strip():
        raise HTTPException(400, detail="device_id is required")
    dev = body.device_id.strip()
    has_pat = bool((body.pat or "").strip())
    res = db.check_account(dev, (body.pat or "").strip() or None)
    branch = res["branch"]
    if branch == "new_account":
        log.info(
            "check_account: NEW account id=%s created, PAT issued=%s, device=%s associated",
            res["account_id"], res["pat"], dev,
        )
    elif branch == "device_found":
        log.info(
            "check_account: known device=%s -> account id=%s, returning stored PAT=%s "
            "(input pat present: %s)",
            dev, res["account_id"], res["pat"], has_pat,
        )
    else:
        log.info(
            "check_account: new device=%s paired to EXISTING account id=%s by supplied PAT",
            dev, res["account_id"],
        )
    return res


@app.post("/photo_input", status_code=202)
def photo_input(
    file: UploadFile = File(...),
    account_id: int = Depends(require_account),
    x_device_id: str | None = Header(default=None),
) -> dict:
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail="upload exceeds 25 MB")
    if not data:
        raise HTTPException(400, detail="empty upload")
    if not _looks_like_image(data):
        raise HTTPException(
            415, detail=f"upload is not a JPEG/PNG/WEBP image (declared {file.content_type!r})"
        )

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    arts = RunArtifacts(cfg.artifacts_dir, run_id)

    ext = (os.path.splitext(file.filename or "")[1].lower() or ".jpg")
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    original_path = os.path.join(arts.dir, f"original{ext}")
    with open(original_path, "wb") as f:
        f.write(data)

    arts.event("api", "accepted", filename=file.filename, bytes=len(data), account_id=account_id)
    arts.write_meta(
        {
            "run_id": run_id,
            "filename": file.filename,
            "content_type": file.content_type,
            "bytes": len(data),
            "account_id": account_id,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
    )

    request_id = db.create_request(account_id, x_device_id, run_id)
    arts.event("api", "queued", request_id=request_id)
    log.info(
        "photo_input: account id=%s device=%s -> request id=%s queued (run=%s, %d bytes)",
        account_id, x_device_id, request_id, run_id, len(data),
    )
    return {"request_id": request_id, "status": "queued", "run_id": run_id}


@app.get("/requests")
def list_requests(account_id: int = Depends(require_account)) -> dict:
    return {"requests": db.list_requests(account_id)}


@app.get("/requests/{request_id}")
def get_request(request_id: int, account_id: int = Depends(require_account)) -> dict:
    req = db.get_request(request_id, account_id)
    if req is None:
        raise HTTPException(404, detail="request not found")
    return req


@app.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: int, account_id: int = Depends(require_account)) -> dict:
    receipt = db.get_receipt(receipt_id, account_id)
    if receipt is None:
        raise HTTPException(404, detail="receipt not found")
    # raw_markdown/ocr_json are bulky; the app page needs header + items only
    receipt.pop("ocr_json", None)
    receipt.pop("structured_json", None)
    return receipt
