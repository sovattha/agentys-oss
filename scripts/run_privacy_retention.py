#!/usr/bin/env python3
# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

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
