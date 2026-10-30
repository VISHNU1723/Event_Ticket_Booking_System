
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from app.database import Base


class Waitlist(Base):
    __tablename__ = "waitlist"

    __table_args__ = (
        UniqueConstraint(
            "show_id",
            "customer_id",
            name="uq_waitlist_show_customer",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    show_id = Column(
        Integer,
        ForeignKey("shows.id"),
        nullable=False,
        index=True,
    )
    customer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    seat_count = Column(Integer, nullable=False)
    preferred_category = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, default="Waiting")
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    notified_at = Column(DateTime, nullable=True)
