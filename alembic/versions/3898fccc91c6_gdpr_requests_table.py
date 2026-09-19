"""gdpr requests table

Revision ID: 3898fccc91c6
Revises: 495720b66c9f
Create Date: 2026-09-19 10:04:04.863732

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3898fccc91c6'
down_revision: Union[str, None] = '495720b66c9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    gdpr_request_type = sa.Enum("suppression", "anonymisation", name="gdpr_request_type")
    gdpr_request_status = sa.Enum("en_attente", "en_cours", "terminee", "echec", name="gdpr_request_status")

    op.create_table(
        "gdpr_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidat_id", sa.Uuid(), nullable=False),
        sa.Column("type", gdpr_request_type, nullable=False),
        sa.Column("statut", gdpr_request_status, server_default="en_attente", nullable=False),
        sa.Column("date_creation", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("date_execution", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resultat_json", sa.JSON(), nullable=True),
        sa.Column("demande_par", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["candidat_id"], ["cvs.id"]),
        sa.ForeignKeyConstraint(["demande_par"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("gdpr_requests")
    sa.Enum(name="gdpr_request_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="gdpr_request_type").drop(op.get_bind(), checkfirst=True)
