
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, func
from app.database import Base


class Refund(Base):
    __tablename__ = "refunds"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id"),
        nullable=False,
        index=True,
    )
    payment_id = Column(
        Integer,
        ForeignKey("payments.id"),
        nullable=True,
    )
    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, default="Refunded")
    refunded_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
