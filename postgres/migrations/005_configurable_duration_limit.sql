BEGIN;

-- The configurable duration policy is enforced by the authenticated API.
-- PostgreSQL continues to enforce the invariant that a reservation has
-- positive duration, while the exclusion constraint protects global overlap.
ALTER TABLE reservations DROP CONSTRAINT IF EXISTS reservation_duration_check;
ALTER TABLE reservations ADD CONSTRAINT reservation_duration_check CHECK (
    end_time > start_time
);

COMMIT;
