-- Roll back only after stopping API/scheduler. It keeps user and reservation data.
BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM teams WHERE ssh_port IS NULL OR ssh_password_legacy IS NULL OR container_name IS NULL) THEN
        RAISE EXCEPTION 'Rollback requires the pre-migration backup: new/rotated users lack legacy credentials';
    END IF;
END $$;
DROP TABLE IF EXISTS service_heartbeats, audit_events, provisioning_jobs, sessions, auth_challenges;
DROP INDEX IF EXISTS reservations_idempotency_idx;
ALTER TABLE reservations DROP COLUMN IF EXISTS idempotency_key;
ALTER TABLE reservations DROP COLUMN IF EXISTS cancellation_reason;
ALTER TABLE reservations DROP COLUMN IF EXISTS cancelled_at;
ALTER TABLE teams DROP COLUMN IF EXISTS last_booking_at;
ALTER TABLE teams DROP COLUMN IF EXISTS provisioning_error;
ALTER TABLE teams DROP COLUMN IF EXISTS provisioning_state;
ALTER TABLE teams DROP COLUMN IF EXISTS display_name;
ALTER TABLE teams DROP COLUMN IF EXISTS volume_name;
ALTER TABLE teams DROP COLUMN IF EXISTS legacy_volume;
ALTER TABLE teams DROP COLUMN IF EXISTS ssh_password_hash;
ALTER TABLE teams RENAME COLUMN ssh_password_legacy TO ssh_password;
ALTER TABLE teams ALTER COLUMN ssh_port SET NOT NULL;
ALTER TABLE teams ALTER COLUMN ssh_password SET NOT NULL;
ALTER TABLE teams ALTER COLUMN container_name SET NOT NULL;
ALTER TABLE teams ALTER COLUMN email TYPE TEXT;
DROP SEQUENCE IF EXISTS ssh_port_seq;
COMMIT;
