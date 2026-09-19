"""cvs table

Revision ID: 88c83420f07f
Revises: fbfe523cf3c8
Create Date: 2026-09-19 09:44:54.526995

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '88c83420f07f'
down_revision: Union[str, None] = 'fbfe523cf3c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


cv_status = sa.Enum("en_cours", "ok", "a_valider", "echec_parsing", "rejete", name="cv_status")


def upgrade() -> None:
    op.create_table(
        "cvs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nom_fichier", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("date_upload", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("statut", cv_status, nullable=False),
        sa.Column("score_confiance_global", sa.Float(), nullable=True),
        sa.Column("donnees_json", sa.JSON(), nullable=True),
        sa.Column("champs_a_verifier", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("cvs")
    cv_status.drop(op.get_bind(), checkfirst=False)
