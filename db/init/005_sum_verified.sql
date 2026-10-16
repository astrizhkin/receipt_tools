-- server-computed boolean: do the stored numbers reconcile (see
-- phunter/verify.py); NULL for rows predating the column until backfilled.
-- apply to existing volumes with psql -f
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS sum_verified BOOLEAN;
