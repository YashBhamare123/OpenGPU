BEGIN;
ALTER TABLE reservations DROP CONSTRAINT IF EXISTS reservation_duration_check;
ALTER TABLE reservations ADD CONSTRAINT reservation_duration_check CHECK (
    end_time > start_time
    AND (duration_override OR end_time <= start_time + INTERVAL '3 hours')
);
COMMIT;
