"""Backfill Claude Haiku 4.5 token usage costs.

Revision ID: 035_backfill_haiku45_costs
Revises: 034_billing_tables
Create Date: 2026-06-09 00:00:01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "035_backfill_haiku45_costs"
down_revision: Union[str, None] = "034_billing_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MODEL = "claude-haiku-4-5-20251001"


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    if table_name not in set(sa.inspect(bind).get_table_names()):
        return set()
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _backfill(*, input_price: float, output_price: float) -> None:
    columns = _columns("token_usage_log")
    if not columns:
        return

    cache_read_expr = (
        "COALESCE(cache_read_input_tokens, 0) * :cache_read_price"
        if "cache_read_input_tokens" in columns
        else "0"
    )
    cache_creation_expr = (
        "COALESCE(cache_creation_input_tokens, 0) * :cache_creation_price"
        if "cache_creation_input_tokens" in columns
        else "0"
    )

    op.execute(
        sa.text(
            f"""
            UPDATE token_usage_log
            SET cost_usd = (
                COALESCE(input_tokens, 0) * :input_price
                + {cache_read_expr}
                + {cache_creation_expr}
                + COALESCE(output_tokens, 0) * :output_price
            ) / 1000000.0
            WHERE model = :model
            """
        ).bindparams(
            input_price=input_price,
            output_price=output_price,
            cache_read_price=input_price * 0.10,
            cache_creation_price=input_price * 1.25,
            model=_MODEL,
        )
    )


def upgrade() -> None:
    _backfill(input_price=1.00, output_price=5.00)


def downgrade() -> None:
    _backfill(input_price=0.80, output_price=4.00)
