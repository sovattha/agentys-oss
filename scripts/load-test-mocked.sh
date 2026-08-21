#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec python scripts/load_test_mocked.py "$@"
