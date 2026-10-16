-- receipt_tools auth + async requests (idempotent; also applied manually to
-- existing volumes with: psql -f db/init/002_auth.sql)

CREATE TABLE IF NOT EXISTS accounts (
    id         BIGSERIAL PRIMARY KEY,
    pat        TEXT NOT NULL UNIQUE,          -- personal access token (uuid4 hex)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devices (
    id         BIGSERIAL PRIMARY KEY,
    device_id  TEXT NOT NULL UNIQUE,          -- client-generated uuid
    account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS requests (
    id            BIGSERIAL PRIMARY KEY,
    account_id    BIGINT NOT NULL REFERENCES accounts(id),
    device_id     TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',  -- queued|running|completed|failed
    stage         TEXT,                           -- resize|ocr|structure|persist
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    status_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    error         TEXT,
    artifacts_dir TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_account ON requests(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status) WHERE status = 'queued';

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS request_id BIGINT REFERENCES requests(id);
