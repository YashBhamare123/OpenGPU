# Testing

## Routine suite

Run through the safety wrapper:

```bash
TEST_MODE=true scripts/run-tests.sh
```

This runs unit and contract tests with Docker and email behavior mocked. Database tests skip when `TEST_DATABASE_URL` is absent.

## Database suite

Create a disposable database whose name ends in `_test`, apply the fresh schema, then run:

```bash
TEST_MODE=true \
TEST_DATABASE_URL=postgresql://user:pass@127.0.0.1/opengpu_test \
scripts/run-tests.sh
```

The safety checks reject a URL whose database name does not end in `_test`. Tests exercise reservation validation, overlap protection, authentication-related rules, and concurrency behavior. Never reuse a development or production database.

## Coverage by area

- `test_security.py`: normalization and non-recoverable secret hashes
- `test_api_contract.py`: authentication/origin/health and request contracts
- `test_database_rules.py`: database constraints and concurrency
- `test_manager.py`: Docker ownership, storage paths, credentials, and provisioning options
- `test_scheduler.py`: desired-state transitions, future containers, and removal behavior

## Static checks

```bash
bash -n start.sh entrypoint.sh scripts/run-tests.sh
python -m py_compile api.py admin.py config.py database.py mailer.py manager.py scheduler.py security.py
docker build --check .
```

## Manual integration checks

Use a non-production user and an idle GPU to verify:

1. OTP login and refresh-persistent session.
2. Initial provisioning followed by successful reservation.
3. Credential email and SSH login.
4. A6000 visibility, CUDA/PyTorch, sudo, Python, Neovim, and tmux.
5. Workspace persistence and stable SSH fingerprint after container recreation.
6. Cancellation and end-time container removal.
7. Failed SMTP/Docker behavior and administrative retry.
8. Scheduler leader exclusivity and readiness degradation.

Do not run container lifecycle or GPU smoke tests while another user's reservation is active.
