"""cv anonymise column and parametres globaux table

Revision ID: 495720b66c9f
Revises: 7cd3bdcd86c0
Create Date: 2026-09-19 09:59:53.692604

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '495720b66c9f'
down_revision: Union[str, None] = '7cd3bdcd86c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cvs", sa.Column("anonymise", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.create_table(
        "parametres_globaux",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("top_k_llm", sa.Integer(), server_default="8", nullable=False),
        sa.Column("anonymisation_par_defaut", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("parametres_globaux")
    op.drop_column("cvs", "anonymise")
