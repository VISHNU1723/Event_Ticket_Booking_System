"""add venue screen and seat layout

Revision ID: 80f63063455a
Revises: f3151520892b
"""

from alembic import op
import sqlalchemy as sa


revision = "80f63063455a"
down_revision = "f3151520892b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "venue_id",
            sa.Integer(),
            sa.ForeignKey("venues.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("total_seats", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "seats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "screen_id",
            sa.Integer(),
            sa.ForeignKey("screens.id"),
            nullable=False,
        ),
        sa.Column("row_label", sa.String(10), nullable=False),
        sa.Column("seat_number", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(30), nullable=False, server_default="Silver"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint(
            "screen_id", "row_label", "seat_number",
            name="uq_screen_row_seat",
        ),
    )


def downgrade() -> None:
    op.drop_table("seats")
    op.drop_table("screens")