# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bulk-action queue: rate-limited, persistent, observable.

Three pieces collaborate:

- `rate_limiter.TokenBucket`  — per-account budget control, honors
  provider Retry-After through `penalize()`.
- `repository.BulkJobRepository` — atomic claim of the next pending
  item via `UPDATE … RETURNING`, counters bumped under WAL.
- `worker.BulkJobWorker`       — long-running background thread that
  spawns one `_AccountQueue` per active account, drains pending items
  through the matching provider, and broadcasts progress via
  `app.api.websocket`.

The HTTP layer (`app.api.routes_bulk_jobs`) and the auto-deletion
scheduler talk to the worker through `enqueue_job()` only — they never
touch SQL directly.

Public surface kept intentionally narrow.
"""

from app.services.bulk_jobs.repository import BulkJobRepository, NewBulkJob
from app.services.bulk_jobs.scheduler import (
    AutoDeletionScheduler,
    init_scheduler,
    run_tick_once,
    shutdown_scheduler,
)
from app.services.bulk_jobs.worker import (
    BulkJobWorker,
    enqueue_job,
    get_worker,
    init_worker,
    shutdown_worker,
)

__all__ = [
    "AutoDeletionScheduler",
    "BulkJobRepository",
    "BulkJobWorker",
    "NewBulkJob",
    "enqueue_job",
    "get_worker",
    "init_scheduler",
    "init_worker",
    "run_tick_once",
    "shutdown_scheduler",
    "shutdown_worker",
]
