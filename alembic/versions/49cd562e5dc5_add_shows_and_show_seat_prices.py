
"""add shows and show seat prices

Revision ID: 49cd562e5dc5
Revises: 80f63063455a
"""

from alembic import op
import sqlalchemy as sa

revision = "49cd562e5dc5"
down_revision = "80f63063455a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shows",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("screen_id", sa.Integer(), sa.ForeignKey("screens.id"), nullable=False),
        sa.Column("show_date", sa.DateTime(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("booking_closes_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Scheduled"),
    )
    op.create_index("ix_shows_id", "shows", ["id"])
    op.create_index("ix_shows_event_id", "shows", ["event_id"])
    op.create_index("ix_shows_screen_id", "shows", ["screen_id"])

    op.create_table(
        "show_seat_prices",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("show_id", sa.Integer(), sa.ForeignKey("shows.id"), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.UniqueConstraint("show_id", "category", name="uq_show_seat_category"),
    )
    op.create_index("ix_show_seat_prices_id", "show_seat_prices", ["id"])
    op.create_index("ix_show_seat_prices_show_id", "show_seat_prices", ["show_id"])


def downgrade() -> None:
    op.drop_index("ix_show_seat_prices_show_id", table_name="show_seat_prices")
    op.drop_index("ix_show_seat_prices_id", table_name="show_seat_prices")
    op.drop_table("show_seat_prices")

    op.drop_index("ix_shows_screen_id", table_name="shows")
    op.drop_index("ix_shows_event_id", table_name="shows")
    op.drop_index("ix_shows_id", table_name="shows")
    op.drop_table("shows")
