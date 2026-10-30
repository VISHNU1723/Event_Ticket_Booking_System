
"""create venue event booking ticket tables"""

from alembic import op
import sqlalchemy as sa

revision = "f3151520892b"
down_revision = "30bd3fd2f081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "Admin", "Organizer", "Customer", "Staff",
                name="user_roles"
            ),
            nullable=False,
            server_default="Customer",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("is_approved", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )

    # Venues
    op.create_table(
        "venues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("city", sa.String(100), nullable=False, server_default=""),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("capacity", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("description", sa.Text(), nullable=True),
    )

    # Events
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("venue_id", sa.Integer(),
                  sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("event_date", sa.DateTime(), nullable=False),
        sa.Column("ticket_price", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("total_tickets", sa.Integer(), nullable=False,
                  server_default="0"),
    )

    # Bookings
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_id", sa.Integer(),
                  sa.ForeignKey("events.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("status", sa.String(30), nullable=False,
                  server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=True,
                  server_default=sa.func.now()),
    )

    # Tickets
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(),
                  sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("event_id", sa.Integer(),
                  sa.ForeignKey("events.id"), nullable=False),
        sa.Column("ticket_code", sa.String(100), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False,
                  server_default="valid"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("tickets")
    op.drop_table("bookings")
    op.drop_table("events")
    op.drop_table("venues")
    op.drop_table("users")
