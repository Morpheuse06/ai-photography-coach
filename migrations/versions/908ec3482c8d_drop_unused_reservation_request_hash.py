"""drop unused reservation request hash

Revision ID: 908ec3482c8d
Revises: 00d5c519db84
Create Date: 2026-08-15 13:24:22.491473

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '908ec3482c8d'
down_revision: Union[str, None] = '00d5c519db84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Older SQLite versions cannot execute ``ALTER TABLE ... DROP COLUMN``.
    # Alembic batch mode recreates the table and copies its data, while other
    # databases still receive an equivalent schema change.
    with op.batch_alter_table('usage_reservations') as batch_op:
        batch_op.drop_column('request_hash')


def downgrade() -> None:
    with op.batch_alter_table('usage_reservations') as batch_op:
        batch_op.add_column(
            sa.Column('request_hash', sa.VARCHAR(length=64), nullable=False)
        )
