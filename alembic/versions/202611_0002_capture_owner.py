"""Capture owner for multi-user mode

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: existing rows and single-user mode have no owner.
    op.add_column("captures", sa.Column("owner", sa.String(length=255), nullable=True))
    op.create_index("ix_captures_owner", "captures", ["owner"])


def downgrade() -> None:
    op.drop_index("ix_captures_owner", table_name="captures")
    op.drop_column("captures", "owner")
