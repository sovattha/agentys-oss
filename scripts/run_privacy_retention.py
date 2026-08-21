#!/usr/bin/env python3
"""Run Agentys privacy retention jobs."""

from __future__ import annotations

import argparse

from app.services.privacy_retention import result_to_json, run_privacy_retention


def main() -> int:
    parser = argparse.ArgumentParser(description="Run privacy retention cleanup")
    parser.add_argument(
        "--redact-logs",
        action="store_true",
        help="Rewrite application log files through the runtime redactor",
    )
    args = parser.parse_args()

    result = run_privacy_retention(redact_logs=args.redact_logs)
    print(result_to_json(result))
    return 0 if not result.warnings else 1


if __name__ == "__main__":
    raise SystemExit(main())
