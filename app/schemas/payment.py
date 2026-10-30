
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class PaymentCreate(BaseModel):
    booking_id: int


class RazorpayOrderResponse(BaseModel):
    payment_id: int
    booking_id: int
    razorpay_order_id: str
    amount: int
    currency: str
    key_id: str


class RazorpayPaymentVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentResponse(BaseModel):
    id: int
    booking_id: int
    transaction_id: str
    amount: Decimal
    payment_method: str
    status: str
    paid_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        orm_mode = True
