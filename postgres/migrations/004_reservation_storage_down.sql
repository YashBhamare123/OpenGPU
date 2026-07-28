BEGIN;
ALTER TABLE reservations DROP CONSTRAINT IF EXISTS reservation_storage_check;
ALTER TABLE reservations DROP COLUMN IF EXISTS temp_storage_gb;
ALTER TABLE reservations DROP COLUMN IF EXISTS workspace_gb;
COMMIT;
