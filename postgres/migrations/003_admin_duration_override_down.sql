-- Refuse rollback while extended reservations exist; shortening user bookings
-- automatically would destroy reservation data.
BEGIN;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM reservations
        WHERE end_time > start_time + INTERVAL '3 hours'
    ) THEN
        RAISE EXCEPTION 'Cannot remove duration override while extended reservations exist';
    END IF;
END $$;
ALTER TABLE reservations DROP CONSTRAINT IF EXISTS reservation_duration_check;
ALTER TABLE reservations ADD CONSTRAINT reservation_duration_check CHECK (
    end_time > start_time AND end_time <= start_time + INTERVAL '3 hours'
);
ALTER TABLE reservations DROP COLUMN IF EXISTS duration_override;
COMMIT;
