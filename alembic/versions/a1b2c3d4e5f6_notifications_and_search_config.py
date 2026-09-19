"""notifications, notification preferences tables and seuil_confiance_min column

Revision ID: a1b2c3d4e5f6
Revises: 3898fccc91c6
Create Date: 2026-09-19 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '3898fccc91c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    notification_type = sa.Enum(
        "cv_echec", "gdpr_terminee", "invitation_envoyee", name="notification_type"
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", notification_type, nullable=False),
        sa.Column("texte", sa.String(length=1024), nullable=False),
        sa.Column("lu", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("date_creation", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.add_column(
        "parametres_globaux",
        sa.Column("seuil_confiance_min", sa.Float(), server_default="0.6", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("parametres_globaux", "seuil_confiance_min")
    op.drop_table("notification_preferences")
    op.drop_table("notifications")
    sa.Enum(name="notification_type").drop(op.get_bind(), checkfirst=True)
