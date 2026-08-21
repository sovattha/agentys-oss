#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

suite="${1:-}"
if [[ -z "$suite" ]]; then
  cat >&2 <<'USAGE'
Usage: scripts/load-test-coverage-suite.sh <suite> [extra runner args...]

Suites:
  soak-mock             Long mock soak at the last known healthy draft tier.
  burst-mock            Burst traffic against the mock draft path.
  full-flow-mock        Mock list/detail + draft + sent-provider flow.
  provider-live-smoke   Low-volume live provider smoke guardrail.
  llm-live-smoke        Low-volume live LLM smoke guardrail.
USAGE
  exit 2
fi
shift || true

case "$suite" in
  soak-mock)
    exec python scripts/load_test_railway_mock.py \
      --scenario draft-users \
      --provider-kind gmail \
      --stages 800 \
      --soak-hours 4 \
      --draft-period-seconds 60 \
      --run-id "soak-mock-$(date +%Y%m%d-%H%M%S)" \
      "$@"
    ;;
  burst-mock)
    exec python scripts/load_test_railway_mock.py \
      --scenario draft-users \
      --provider-kind gmail \
      --stages 400,800,1200 \
      --stage-seconds 120 \
      --traffic-shape burst \
      --burst-window-seconds 5 \
      --draft-period-seconds 60 \
      --run-id "burst-mock-$(date +%Y%m%d-%H%M%S)" \
      "$@"
    ;;
  full-flow-mock)
    exec python scripts/load_test_railway_mock.py \
      --scenario full-flow \
      --provider-kind gmail \
      --stages 100,400,800 \
      --stage-seconds 180 \
      --draft-period-seconds 60 \
      --provider-list-limit 20 \
      --run-id "full-flow-mock-$(date +%Y%m%d-%H%M%S)" \
      "$@"
    ;;
  provider-live-smoke)
    exec python scripts/load_test_railway_mock.py \
      --scenario provider \
      --provider-mode live \
      --allow-live-services \
      --stages 5,10,25 \
      --stage-seconds 120 \
      --provider-period-seconds 60 \
      --run-id "provider-live-smoke-$(date +%Y%m%d-%H%M%S)" \
      "$@"
    ;;
  llm-live-smoke)
    exec python scripts/load_test_railway_mock.py \
      --scenario draft-users \
      --llm-mode live \
      --allow-live-services \
      --stages 5,10,25 \
      --stage-seconds 120 \
      --draft-period-seconds 120 \
      --run-id "llm-live-smoke-$(date +%Y%m%d-%H%M%S)" \
      "$@"
    ;;
  *)
    echo "Unknown suite: $suite" >&2
    exit 2
    ;;
esac
