# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Quick Steps — deterministic action chains for email triage.

A Quick Step is a user-defined sequence of email actions (archive, label,
forward, reply with template, etc.) executed in one keypress. No LLM calls.

Public surface:
- ``schema.validate_quick_step`` — input validation
- ``store.load_quick_steps`` / ``store.save_quick_steps`` — DB persistence
- ``engine.execute`` — run a chain on one email
- ``registry.ACTION_HANDLERS`` — action dispatch table
"""
