BEGIN;

ALTER TABLE provisioning_jobs
    DROP CONSTRAINT IF EXISTS provisioning_jobs_purpose_check;
ALTER TABLE provisioning_jobs
    DROP COLUMN IF EXISTS purpose;

COMMIT;
