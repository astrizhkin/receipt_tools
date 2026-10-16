-- auto-retry of failed requests (apply to existing volumes with psql -f)
ALTER TABLE requests ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;
