
"""add booking and booked seats

Revision ID: 3112c3b48ec8
Revises: dffb82d4e5b1
"""

from alembic import op
import sqlalchemy as sa

revision = "3112c3b48ec8"
down_revision = "dffb82d4e5b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep legacy booking columns to preserve compatibility.
    # Add new columns as nullable first for safe schema evolution.
    op.add_column(
        "bookings",
        sa.Column("booking_number", sa.String(30), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("customer_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("show_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("seat_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("ticket_total", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("convenience_fee", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("gst_amount", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("grand_total", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )

    # Unique booking number.
    op.create_index(
        "ix_bookings_booking_number",
        "bookings",
        ["booking_number"],
        unique=True,
    )
    op.create_index(
        "ix_bookings_customer_id",
        "bookings",
        ["customer_id"],
    )
    op.create_index(
        "ix_bookings_show_id",
        "bookings",
        ["show_id"],
    )

    # New booked seats table. Seat conflicts are checked by the
    # booking service, allowing seats to be booked again after expiry
    # or cancellation.
    op.create_table(
        "booked_seats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "booking_id",
            sa.Integer(),
            sa.ForeignKey("bookings.id"),
            nullable=False,
        ),
        sa.Column(
            "show_id",
            sa.Integer(),
            sa.ForeignKey("shows.id"),
            nullable=False,
        ),
        sa.Column(
            "seat_id",
            sa.Integer(),
            sa.ForeignKey("seats.id"),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
    )

    op.create_index(
        "ix_booked_seats_booking_id",
        "booked_seats",
        ["booking_id"],
    )
    op.create_index(
        "ix_booked_seats_show_id",
        "booked_seats",
        ["show_id"],
    )
    op.create_index(
        "ix_booked_seats_seat_id",
        "booked_seats",
        ["seat_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_booked_seats_seat_id",
        table_name="booked_seats",
    )
    op.drop_index(
        "ix_booked_seats_show_id",
        table_name="booked_seats",
    )
    op.drop_index(
        "ix_booked_seats_booking_id",
        table_name="booked_seats",
    )
    op.drop_table("booked_seats")

    op.drop_index(
        "ix_bookings_show_id",
        table_name="bookings",
    )
    op.drop_index(
        "ix_bookings_customer_id",
        table_name="bookings",
    )
    op.drop_index(
        "ix_bookings_booking_number",
        table_name="bookings",
    )

    op.drop_column("bookings", "confirmed_at")
    op.drop_column("bookings", "expires_at")
    op.drop_column("bookings", "grand_total")
    op.drop_column("bookings", "gst_amount")
    op.drop_column("bookings", "convenience_fee")
    op.drop_column("bookings", "ticket_total")
    op.drop_column("bookings", "seat_count")
    op.drop_column("bookings", "show_id")
    op.drop_column("bookings", "customer_id")
    op.drop_column("bookings", "booking_number")
