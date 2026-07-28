BEGIN;

ALTER TABLE reservations
    ADD COLUMN IF NOT EXISTS workspace_gb INTEGER NOT NULL DEFAULT 2,
    ADD COLUMN IF NOT EXISTS temp_storage_gb INTEGER NOT NULL DEFAULT 100;

ALTER TABLE reservations DROP CONSTRAINT IF EXISTS reservation_storage_check;
ALTER TABLE reservations ADD CONSTRAINT reservation_storage_check CHECK (
    workspace_gb >= 1 AND temp_storage_gb >= 1 AND workspace_gb + temp_storage_gb <= 200
);

COMMIT;
