
from datetime import datetime
from decimal import Decimal
from typing import List

from pydantic import BaseModel, Field


class BookingCreate(BaseModel):
    show_id: int = Field(..., gt=0)
    seat_ids: List[int] = Field(..., min_items=1)


class BookedSeatResponse(BaseModel):
    seat_id: int
    price: Decimal


class BookingResponse(BaseModel):
    id: int
    booking_number: str
    customer_id: int
    show_id: int
    seat_count: int
    ticket_total: Decimal
    convenience_fee: Decimal
    gst_amount: Decimal
    grand_total: Decimal
    status: str
    expires_at: datetime
    confirmed_at: datetime = None
    booked_seats: List[BookedSeatResponse]

    class Config:
        orm_mode = True
