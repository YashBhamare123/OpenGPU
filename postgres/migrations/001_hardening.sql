-- Apply once to the prototype database after taking a backup.
BEGIN;
CREATE EXTENSION IF NOT EXISTS citext;
ALTER TABLE teams ALTER COLUMN email TYPE CITEXT;
ALTER TABLE teams ALTER COLUMN ssh_port DROP NOT NULL;
ALTER TABLE teams ALTER COLUMN ssh_password DROP NOT NULL;
ALTER TABLE teams ALTER COLUMN container_name DROP NOT NULL;
-- Retain the old value only for rollback during the controlled migration window.
-- The application never reads this column; it is cleared after successful rotation.
ALTER TABLE teams RENAME COLUMN ssh_password TO ssh_password_legacy;
ALTER TABLE teams ADD COLUMN ssh_password_hash TEXT;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS volume_name TEXT UNIQUE;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS legacy_volume BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE teams SET volume_name = name || '-workspace', legacy_volume = TRUE WHERE volume_name IS NULL;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS provisioning_state TEXT NOT NULL DEFAULT 'ready';
ALTER TABLE teams ADD COLUMN IF NOT EXISTS provisioning_error TEXT;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS last_booking_at TIMESTAMPTZ;
ALTER TABLE reservations ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;
ALTER TABLE reservations ADD COLUMN IF NOT EXISTS cancellation_reason TEXT;
ALTER TABLE reservations ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS reservations_idempotency_idx
    ON reservations(team_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE SEQUENCE IF NOT EXISTS ssh_port_seq START 22001;
SELECT setval('ssh_port_seq', GREATEST(22001, COALESCE((SELECT MAX(ssh_port) + 1 FROM teams), 22001)), false);

CREATE TABLE auth_challenges (
    id BIGSERIAL PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    used_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE sessions (
    id BIGSERIAL PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL, expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE provisioning_jobs (
    id BIGSERIAL PRIMARY KEY, team_id INTEGER UNIQUE NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL DEFAULT 'initial' CHECK (purpose IN ('initial','reservation','admin')),
    state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE audit_events (
    id BIGSERIAL PRIMARY KEY, team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL, details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE service_heartbeats (
    service_name TEXT PRIMARY KEY, last_seen_at TIMESTAMPTZ NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
COMMIT;
