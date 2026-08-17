-- Fresh-install schema. Existing installations must use migrations/001_hardening.sql.
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS teams (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE,
    email CITEXT UNIQUE,
    handle CITEXT UNIQUE,
    display_name TEXT,
    ssh_port INTEGER UNIQUE,
    ssh_password_hash TEXT,
    ssh_public_key TEXT,
    container_name TEXT UNIQUE,
    volume_name TEXT UNIQUE,
    legacy_volume BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    provisioning_state TEXT NOT NULL DEFAULT 'unprovisioned'
        CHECK (provisioning_state IN ('unprovisioned','pending','ready','failed','disabled')),
    provisioning_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_booking_at TIMESTAMPTZ,
    CONSTRAINT teams_identity_check CHECK (email IS NOT NULL OR handle IS NOT NULL)
);

CREATE SEQUENCE IF NOT EXISTS ssh_port_seq START 22001;

CREATE TABLE IF NOT EXISTS reservations (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    cancelled BOOLEAN NOT NULL DEFAULT FALSE,
    cancelled_at TIMESTAMPTZ,
    cancellation_reason TEXT,
    idempotency_key TEXT,
    duration_override BOOLEAN NOT NULL DEFAULT FALSE,
    workspace_gb INTEGER NOT NULL DEFAULT 2,
    temp_storage_gb INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT reservation_storage_check CHECK (
        workspace_gb >= 1 AND temp_storage_gb >= 1 AND workspace_gb + temp_storage_gb <= 200
    ),
    CONSTRAINT reservation_duration_check CHECK (
        end_time > start_time
    ),
    CONSTRAINT no_overlapping_reservations EXCLUDE USING gist (
        tstzrange(start_time, end_time, '[)') WITH &&
    ) WHERE (cancelled = FALSE),
    UNIQUE (team_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS share_claims (
    id BIGSERIAL PRIMARY KEY,
    token_hash TEXT UNIQUE NOT NULL,
    suggested_handle CITEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    consumed_team_id BIGINT REFERENCES teams(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth_challenges (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS provisioning_jobs (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT UNIQUE NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL DEFAULT 'initial' CHECK (purpose IN ('initial','reservation','admin')),
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','running','done','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT REFERENCES teams(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS service_heartbeats (
    service_name TEXT PRIMARY KEY,
    last_seen_at TIMESTAMPTZ NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE OR REPLACE FUNCTION validate_reservation() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.cancelled THEN RETURN NEW; END IF;
    IF NEW.start_time < NOW() THEN RAISE EXCEPTION 'Reservation cannot start in the past'; END IF;
    PERFORM 1 FROM teams WHERE id = NEW.team_id AND enabled FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'User is disabled or missing'; END IF;
    IF EXISTS (
        SELECT 1 FROM reservations
        WHERE team_id = NEW.team_id AND end_time > NOW() AND NOT cancelled
          AND id IS DISTINCT FROM NEW.id
    ) THEN RAISE EXCEPTION 'User already has a current or future reservation'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS validate_reservation_trigger ON reservations;
CREATE TRIGGER validate_reservation_trigger BEFORE INSERT OR UPDATE ON reservations
FOR EACH ROW EXECUTE FUNCTION validate_reservation();
