-- BB-GA-4.1 / REQ — schema_migrations audit table.
-- Idempotent: safe to run on every service start; first runner to win the
-- bootstrap advisory lock creates the table, others see IF NOT EXISTS and skip.

CREATE TABLE IF NOT EXISTS schema_migrations (
    id              BIGSERIAL PRIMARY KEY,
    service_name    TEXT        NOT NULL,
    migration_id    TEXT        NOT NULL,
    file_checksum   TEXT        NOT NULL,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_by      TEXT        NOT NULL,
    duration_ms     INTEGER     NOT NULL,
    success         BOOLEAN     NOT NULL,
    error_message   TEXT,
    UNIQUE (service_name, migration_id, success)
);

CREATE INDEX IF NOT EXISTS schema_migrations_service_applied_at_idx
    ON schema_migrations (service_name, applied_at DESC);
