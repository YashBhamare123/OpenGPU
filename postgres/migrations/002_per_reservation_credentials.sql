BEGIN;

ALTER TABLE provisioning_jobs
    ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT 'initial';

ALTER TABLE provisioning_jobs
    DROP CONSTRAINT IF EXISTS provisioning_jobs_purpose_check;

ALTER TABLE provisioning_jobs
    ADD CONSTRAINT provisioning_jobs_purpose_check
    CHECK (purpose IN ('initial','reservation','admin'));

COMMIT;
