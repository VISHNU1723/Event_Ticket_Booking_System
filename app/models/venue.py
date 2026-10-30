from sqlalchemy import (
    Column, Integer, String, Text, Boolean,
    ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship

from app.database import Base


class Venue(Base):
    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    city = Column(String(100), nullable=False, default="")
    address = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    capacity = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)

    screens = relationship(
        "Screen",
        back_populates="venue",
        cascade="all, delete-orphan"
    )


class Screen(Base):
    __tablename__ = "screens"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(
        Integer, ForeignKey("venues.id"), nullable=False, index=True
    )
    name = Column(String(150), nullable=False)
    total_seats = Column(Integer, nullable=False, default=0)

    venue = relationship("Venue", back_populates="screens")
    seats = relationship(
        "Seat",
        back_populates="screen",
        cascade="all, delete-orphan"
    )


class Seat(Base):
    __tablename__ = "seats"

    __table_args__ = (
        UniqueConstraint(
            "screen_id", "row_label", "seat_number",
            name="uq_screen_row_seat"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    screen_id = Column(
        Integer, ForeignKey("screens.id"), nullable=False, index=True
    )
    row_label = Column(String(10), nullable=False)
    seat_number = Column(Integer, nullable=False)
    category = Column(String(30), nullable=False, default="Silver")
    is_active = Column(Boolean, nullable=False, default=True)

    screen = relationship("Screen", back_populates="seats")