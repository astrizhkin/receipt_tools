-- per-line + receipt-level discounts (r-keeper receipts print a Скидка
-- under each line and a total Скидка; apply to existing volumes with psql -f)
ALTER TABLE receipt_items ADD COLUMN IF NOT EXISTS discount NUMERIC(12,2);
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS discount_total NUMERIC(12,2);
