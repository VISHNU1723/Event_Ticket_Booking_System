
"""update events for level 4

Revision ID: dffb82d4e5b1
Revises: 49cd562e5dc5
"""

from alembic import op
import sqlalchemy as sa

revision = "dffb82d4e5b1"
down_revision = "49cd562e5dc5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("organizer_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_organizer_id_users",
        "events",
        "users",
        ["organizer_id"],
        ["id"],
    )
    op.create_index("ix_events_organizer_id", "events", ["organizer_id"])

    op.add_column(
        "events",
        sa.Column("category", sa.String(length=30), nullable=False, server_default="Movie"),
    )
    op.add_column(
        "events",
        sa.Column("language", sa.String(length=50), nullable=False, server_default="English"),
    )
    op.add_column(
        "events",
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="120"),
    )
    op.add_column(
        "events",
        sa.Column("age_rating", sa.String(length=10), nullable=False, server_default="U"),
    )
    op.add_column(
        "events",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Draft"),
    )


def downgrade() -> None:
    op.drop_column("events", "status")
    op.drop_column("events", "age_rating")
    op.drop_column("events", "duration_minutes")
    op.drop_column("events", "language")
    op.drop_column("events", "category")
    op.drop_index("ix_events_organizer_id", table_name="events")
    op.drop_constraint(
        "fk_events_organizer_id_users",
        "events",
        type_="foreignkey",
    )
    op.drop_column("events", "organizer_id")
