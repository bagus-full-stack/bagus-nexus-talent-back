"""synonymes competences table

Revision ID: 7cd3bdcd86c0
Revises: 88c83420f07f
Create Date: 2026-09-19 09:52:22.940145

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7cd3bdcd86c0'
down_revision: Union[str, None] = '88c83420f07f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "synonymes_competences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("terme_a", sa.String(length=255), nullable=False),
        sa.Column("terme_b", sa.String(length=255), nullable=False),
        sa.Column("type_entite", sa.String(length=50), server_default="competence", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("synonymes_competences")
