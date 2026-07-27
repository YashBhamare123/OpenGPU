#!/usr/bin/env bash
set -euo pipefail

if [[ "${TEST_MODE:-}" != "true" ]]; then
  echo "Refusing to run: set TEST_MODE=true" >&2
  exit 2
fi

if [[ -n "${TEST_DATABASE_URL:-}" && "${TEST_DATABASE_URL%%\?*}" != *_test ]]; then
  echo "Refusing to run against a database not ending in _test" >&2
  exit 2
fi

python3 -m pytest -q
