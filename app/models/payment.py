
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


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)

    booking_id = Column(
        Integer,
        ForeignKey("bookings.id"),
        nullable=False,
        index=True,
    )

    transaction_id = Column(
        String(40),
        unique=True,
        nullable=False,
        index=True,
    )

    amount = Column(Numeric(10, 2), nullable=False)
    payment_method = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default="Failed")
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    booking = relationship("Booking")
