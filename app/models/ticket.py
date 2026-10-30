
from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    DateTime,
    func,
)
from app.database import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id"),
        nullable=False,
        index=True,
    )
    event_id = Column(
        Integer,
        ForeignKey("events.id"),
        nullable=False,
    )
    ticket_code = Column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    qr_token = Column(String(500), nullable=True)
    status = Column(
        String(30),
        nullable=False,
        default="valid",
        index=True,
    )
    scanned_at = Column(DateTime, nullable=True)
    scanned_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
