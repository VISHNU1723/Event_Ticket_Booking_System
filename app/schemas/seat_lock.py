
from typing import List
from pydantic import BaseModel, Field


class SeatLockRequest(BaseModel):
    seat_ids: List[int] = Field(..., min_items=1)


class SeatLockResponse(BaseModel):
    show_id: int
    seat_ids: List[int]
    status: str
    expires_at: str
    message: str
