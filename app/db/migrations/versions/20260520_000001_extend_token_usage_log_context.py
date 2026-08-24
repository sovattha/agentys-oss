# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Extend token_usage_log with cache and request context.

Revision ID: 031_token_usage_context
Revises: 030_purge_email_content_cache
Create Date: 2026-05-20 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "031_token_usage_context"
down_revision: Union[str, None] = "030_purge_email_content_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    if table_name not in set(sa.inspect(bind).get_table_names()):
        return set()
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name in _columns(table_name):
        return
    op.add_column(table_name, column)


def upgrade() -> None:
    if not _columns("token_usage_log"):
        return

    _add_column_if_missing(
        "token_usage_log",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        "token_usage_log",
        sa.Column("feature", sa.String(length=64), nullable=False, server_default="unknown"),
    )
    _add_column_if_missing(
        "token_usage_log",
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "token_usage_log",
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )

    bind = op.get_bind()
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("token_usage_log")
    }
    if "ix_token_usage_log_user_created" not in indexes:
        op.create_index(
            "ix_token_usage_log_user_created",
            "token_usage_log",
            ["user_id", "created_at"],
        )
    if "ix_token_usage_log_feature_created" not in indexes:
        op.create_index(
            "ix_token_usage_log_feature_created",
            "token_usage_log",
            ["feature", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "token_usage_log" not in set(sa.inspect(bind).get_table_names()):
        return
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("token_usage_log")
    }
    if "ix_token_usage_log_feature_created" in indexes:
        op.drop_index("ix_token_usage_log_feature_created", table_name="token_usage_log")
    if "ix_token_usage_log_user_created" in indexes:
        op.drop_index("ix_token_usage_log_user_created", table_name="token_usage_log")

    existing = _columns("token_usage_log")
    for column_name in (
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "feature",
        "user_id",
    ):
        if column_name in existing:
            op.drop_column("token_usage_log", column_name)
