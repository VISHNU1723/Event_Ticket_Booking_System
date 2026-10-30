
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey,
    UniqueConstraint
)
from sqlalchemy.orm import relationship

from app.database import Base


class Show(Base):
    __tablename__ = "shows"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(
        Integer, ForeignKey("events.id"), nullable=False, index=True
    )
    screen_id = Column(
        Integer, ForeignKey("screens.id"), nullable=False, index=True
    )
    show_date = Column(DateTime, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    booking_closes_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="Scheduled")

    event = relationship("Event", foreign_keys=[event_id])
    screen = relationship("Screen", foreign_keys=[screen_id])
    category_prices = relationship(
        "ShowSeatPrice",
        back_populates="show",
        cascade="all, delete-orphan",
    )


class ShowSeatPrice(Base):
    __tablename__ = "show_seat_prices"

    __table_args__ = (
        UniqueConstraint(
            "show_id", "category", name="uq_show_seat_category"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    show_id = Column(
        Integer, ForeignKey("shows.id"), nullable=False, index=True
    )
    category = Column(String(30), nullable=False)
    price = Column(Integer, nullable=False)

    show = relationship("Show", back_populates="category_prices")
