-- Allow an authenticated administrator to explicitly exempt one reservation
-- from the normal three-hour limit. Application authorization remains required.
BEGIN;
ALTER TABLE reservations
    ADD COLUMN IF NOT EXISTS duration_override BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE reservations DROP CONSTRAINT IF EXISTS reservation_duration_check;
ALTER TABLE reservations ADD CONSTRAINT reservation_duration_check CHECK (
    end_time > start_time
    AND (duration_override OR end_time <= start_time + INTERVAL '3 hours')
);
COMMIT;
