-- price_hunter receipt schema (applied on first postgres start)

CREATE TABLE IF NOT EXISTS receipts (
    id            BIGSERIAL PRIMARY KEY,
    run_id        TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    image_path    TEXT,
    store_name    TEXT,
    receipt_date  TEXT,
    total         NUMERIC(12, 2),
    currency      TEXT NOT NULL DEFAULT 'RUB',
    raw_markdown  TEXT,
    ocr_json      JSONB,
    structured_json JSONB
);

CREATE TABLE IF NOT EXISTS receipt_items (
    id         BIGSERIAL PRIMARY KEY,
    receipt_id BIGINT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    position   INT,
    name       TEXT,
    qty        NUMERIC(12, 3),
    unit       TEXT,
    price      NUMERIC(12, 2),
    sum        NUMERIC(12, 2),
    tax        TEXT
);

CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt ON receipt_items(receipt_id);
CREATE INDEX IF NOT EXISTS idx_receipts_store ON receipts(store_name);
