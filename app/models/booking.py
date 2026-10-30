
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Numeric,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)

    # Legacy columns retained for compatibility
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    quantity = Column(Integer, nullable=True, default=1)

    # New booking fields
    booking_number = Column(String(30), unique=True, nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    show_id = Column(Integer, ForeignKey("shows.id"), nullable=True, index=True)

    seat_count = Column(Integer, nullable=True)
    ticket_total = Column(Numeric(10, 2), nullable=True)
    convenience_fee = Column(Numeric(10, 2), nullable=True)
    gst_amount = Column(Numeric(10, 2), nullable=True)
    grand_total = Column(Numeric(10, 2), nullable=True)

    status = Column(
        String(30),
        nullable=False,
        default="Pending Payment",
        index=True,
    )

    expires_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    reminder_sent_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    booked_seats = relationship(
        "BookedSeat",
        back_populates="booking",
        cascade="all, delete-orphan",
    )


class BookedSeat(Base):
    __tablename__ = "booked_seats"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id"),
        nullable=False,
        index=True,
    )
    show_id = Column(
        Integer,
        ForeignKey("shows.id"),
        nullable=False,
        index=True,
    )
    seat_id = Column(
        Integer,
        ForeignKey("seats.id"),
        nullable=False,
        index=True,
    )
    price = Column(Numeric(10, 2), nullable=False)

    booking = relationship("Booking", back_populates="booked_seats")
