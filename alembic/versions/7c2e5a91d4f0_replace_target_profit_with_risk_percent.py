"""replace target_profit with risk_percent

Revision ID: 7c2e5a91d4f0
Revises: 3f43cca953db
Create Date: 2026-10-11 16:00:00.000000

The openers are now sized from a risk percentage of capital, and adder_profit
(the one strategy that read target_profit) is gone. target_profit and
target_profit_percent stay as nullable legacy columns, the second_entry
precedent: stored rows keep their data.

Live adder_profit rows can no longer be rebuilt, because the domain no longer
knows the strategy. At a $0 target adder_profit was identical to
adder_breakeven, so those rows are relabelled. Above $0 they were not, so they
are soft-deleted -- nothing is dropped, and the downgrade does not restore
them.

Downgrading restores NOT NULL on target_profit, which fails once a row written
after this revision exists. That is inherent to a nullable migration.
"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2e5a91d4f0'
down_revision: Union[str, Sequence[str], None] = '3f43cca953db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('simulations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('risk_percent', sa.Float(), nullable=True))
        batch_op.alter_column('target_profit', existing_type=sa.Float(), nullable=True)
        batch_op.alter_column(
            'strategy',
            existing_type=sa.String(length=20),
            server_default='adder_breakeven',
            existing_server_default='adder_profit',
        )

    simulations = sa.table(
        'simulations',
        sa.column('strategy', sa.String),
        sa.column('target_profit', sa.Float),
        sa.column('deleted_at', sa.DateTime(timezone=True)),
    )
    live_profit = sa.and_(
        simulations.c.strategy == 'adder_profit', simulations.c.deleted_at.is_(None)
    )
    op.execute(
        simulations.update()
        .where(live_profit, simulations.c.target_profit == 0)
        .values(strategy='adder_breakeven')
    )
    op.execute(
        simulations.update().where(live_profit).values(deleted_at=datetime.now(UTC))
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('simulations', schema=None) as batch_op:
        batch_op.alter_column(
            'strategy',
            existing_type=sa.String(length=20),
            server_default='adder_profit',
            existing_server_default='adder_breakeven',
        )
        batch_op.alter_column('target_profit', existing_type=sa.Float(), nullable=False)
        batch_op.drop_column('risk_percent')
