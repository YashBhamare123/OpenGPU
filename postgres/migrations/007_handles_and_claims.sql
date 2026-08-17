BEGIN;

ALTER TABLE teams ADD COLUMN IF NOT EXISTS handle CITEXT;
ALTER TABLE teams ALTER COLUMN email DROP NOT NULL;

UPDATE teams SET handle = 'gpu' || id::text WHERE handle IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'teams_handle_key'
    ) THEN
        ALTER TABLE teams ADD CONSTRAINT teams_handle_key UNIQUE (handle);
    END IF;
END $$;

ALTER TABLE teams DROP CONSTRAINT IF EXISTS teams_identity_check;
ALTER TABLE teams ADD CONSTRAINT teams_identity_check
    CHECK (email IS NOT NULL OR handle IS NOT NULL);

CREATE TABLE IF NOT EXISTS share_claims (
    id BIGSERIAL PRIMARY KEY,
    token_hash TEXT UNIQUE NOT NULL,
    suggested_handle CITEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    consumed_team_id BIGINT REFERENCES teams(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
