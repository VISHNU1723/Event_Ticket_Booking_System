
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Float,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)

    # Organizer who owns the event
    organizer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    # Event details
    title = Column(String(150), nullable=False)
    category = Column(String(30), nullable=False, default="Movie")
    language = Column(String(50), nullable=False, default="English")
    description = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=False, default=120)
    age_rating = Column(String(10), nullable=False, default="U")
    status = Column(String(20), nullable=False, default="Draft")

    # Existing fields retained for compatibility
    venue_id = Column(
        Integer,
        ForeignKey("venues.id"),
        nullable=False,
    )
    event_date = Column(DateTime, nullable=False)
    ticket_price = Column(Float, nullable=False, default=0.0)
    total_tickets = Column(Integer, nullable=False, default=0)

    # Relationships
    organizer = relationship("User", foreign_keys=[organizer_id])
    venue = relationship("Venue", foreign_keys=[venue_id])
