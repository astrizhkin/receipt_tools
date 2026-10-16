"""DB-backed tests for auth + request lifecycle.

Run against a scratch DB:
    PH_TEST_DB_DSN=postgresql://... docker run --rm phunter-test
Skipped when PH_TEST_DB_DSN is unset.
"""
import os
import uuid

import psycopg
import pytest

from phunter.db import ReceiptDB

DSN = os.environ.get("PH_TEST_DB_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="PH_TEST_DB_DSN not set")


@pytest.fixture()
def db():
    with psycopg.connect(DSN) as conn:
        conn.execute("TRUNCATE receipt_items, receipts, requests, devices, accounts RESTART IDENTITY CASCADE")
        conn.commit()
    return ReceiptDB(DSN)


def _dev() -> str:
    return "t-" + uuid.uuid4().hex


# ---- check_account matrix ---------------------------------------------------

def test_new_device_no_pat_creates_everything(db):
    r = db.check_account(_dev(), None)
    assert r["is_new"] is True
    assert len(r["pat"]) == 32
    assert db.authenticate(r["pat"], _dev()) is None  # other device not paired


def test_known_device_null_pat_returns_stored(db):
    dev = _dev()
    first = db.check_account(dev, None)
    again = db.check_account(dev, None)
    assert again["pat"] == first["pat"]
    assert again["is_new"] is False


def test_known_device_wrong_pat_still_returns_stored(db):
    """Deliberate security debt per spec: stored pat wins regardless."""
    dev = _dev()
    first = db.check_account(dev, None)
    again = db.check_account(dev, "deadbeef" * 4)
    assert again["pat"] == first["pat"]
    assert again["is_new"] is False


def test_new_device_valid_pat_pairs_device(db):
    dev1, dev2 = _dev(), _dev()
    first = db.check_account(dev1, None)
    second = db.check_account(dev2, first["pat"])
    assert second["pat"] == first["pat"]
    assert second["account_id"] == first["account_id"]
    assert db.authenticate(first["pat"], dev2) == first["account_id"]


def test_authenticate_strict_pair(db):
    dev1, dev2 = _dev(), _dev()
    a = db.check_account(dev1, None)
    b = db.check_account(dev2, None)
    assert db.authenticate(a["pat"], dev1) == a["account_id"]
    assert db.authenticate(a["pat"], dev2) is None
    assert db.authenticate(b["pat"], dev1) is None
    assert db.authenticate(None, dev1) is None


# ---- request lifecycle --------------------------------------------------------

def test_recover_interrupted_requeues_running(db):
    dev = _dev()
    acct = db.check_account(dev, None)
    rid = db.create_request(acct["account_id"], dev, "/artifacts/y")
    db.claim_next_queued()  # -> running (simulates a crash mid-pipeline)

    recovered = db.recover_interrupted()
    assert recovered == [rid]
    back = db.get_request(rid, acct["account_id"])
    assert back["status"] == "queued" and back["stage"] is None

    again = db.claim_next_queued()
    assert again and again["id"] == rid and again["status"] == "running"


def test_apply_migrations_tracks_files(db, tmp_path):
    # the fixture doesn't truncate schema_migrations; clear our row so the
    # test is idempotent across runs against the same scratch DB
    with psycopg.connect(DSN) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                     "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        conn.execute("DELETE FROM schema_migrations WHERE filename = '001_mig.sql'")
        conn.commit()
    (tmp_path / "001_mig.sql").write_text("CREATE TABLE IF NOT EXISTS mig_probe (id INT);")
    assert db.apply_migrations(str(tmp_path)) == ["001_mig.sql"]
    assert db.apply_migrations(str(tmp_path)) == []  # tracked, not re-run
    with psycopg.connect(DSN) as conn:
        conn.execute("SELECT count(*) FROM mig_probe")
        conn.execute("DROP TABLE mig_probe")
        conn.commit()


def test_requeue_failed_picks_oldest_and_caps(db):
    """Longest-waited (oldest status_at) failed request is retried; each
    failure refreshes status_at, so retries round-robin until the cap."""
    dev = _dev()
    acct = db.check_account(dev, None)
    r1 = db.create_request(acct["account_id"], dev, "/artifacts/a")
    r2 = db.create_request(acct["account_id"], dev, "/artifacts/b")

    def fail(rid):
        assert db.claim_next_queued()["id"] == rid
        db.finish_request(rid, "failed", error="boom")

    fail(r1)  # r1 failed first (older status_at)
    fail(r2)

    for expected in ((r1, 1), (r2, 1), (r1, 2), (r2, 2)):
        got = db.requeue_failed(max_retries=2)
        assert got and got["id"] == expected[0] and got["retry_count"] == expected[1]
        fail(got["id"])

    # both exhausted at the cap
    assert db.requeue_failed(max_retries=2) is None
    assert db.requeue_failed(max_retries=0) is None


def test_finish_request_exhaust_retries_blocks_requeue(db):
    """Deterministic failures (e.g. LLM output truncation) are finished with
    retry_count at the cap so the queue-drain requeue skips them forever."""
    dev = _dev()
    acct = db.check_account(dev, None)
    rid = db.create_request(acct["account_id"], dev, "/artifacts/trunc")
    db.finish_request(rid, "failed", error="truncated", exhaust_retries=3)
    assert db.requeue_failed(max_retries=3) is None


def test_request_lifecycle(db):
    dev = _dev()
    acct = db.check_account(dev, None)
    rid = db.create_request(acct["account_id"], dev, "/artifacts/x")

    assert db.get_request(rid, acct["account_id"])["status"] == "queued"

    claimed = db.claim_next_queued()
    assert claimed and claimed["id"] == rid and claimed["status"] == "running"
    assert db.claim_next_queued() is None  # nothing else queued

    db.set_request_stage(rid, "ocr")
    mid = db.get_request(rid, acct["account_id"])
    assert mid["stage"] == "ocr" and mid["status"] == "running"
    assert mid["duration_s"] is not None

    db.finish_request(rid, "completed")
    done = db.get_request(rid, acct["account_id"])
    assert done["status"] == "completed" and done["finished_at"]

    listed = db.list_requests(acct["account_id"])
    assert len(listed) == 1 and listed[0]["id"] == rid
    # other accounts cannot see it
    other = db.check_account(_dev(), None)
    assert db.get_request(rid, other["account_id"]) is None
    assert db.list_requests(other["account_id"]) == []
