"""add deployment callback_token_hash

Revision ID: a1b2c3d4e5f6
Revises: 0df7d52d849c
Create Date: 2026-08-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0df7d52d849c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('deployments', sa.Column('callback_token_hash', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('deployments', 'callback_token_hash')
