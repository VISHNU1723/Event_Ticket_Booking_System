
import os
import hmac
import hashlib
import logging
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import razorpay

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.router import get_current_user
from app.models.user import User
from app.models.booking import Booking
from app.models.payment import Payment
from app.models.ticket import Ticket
from app.services.redis_client import redis_client
from app.services.seat_lock_service import lock_key
from app.services.ticket_service import generate_ticket_pdf
from app.services.notification_service import send_email_notification
from app.websockets.manager import seat_ws_manager


router = APIRouter(tags=["Payments"])
logger = logging.getLogger(__name__)


def get_razorpay_client():
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        raise HTTPException(
            status_code=500,
            detail="Razorpay API keys are not configured",
        )

    return razorpay.Client(auth=(key_id, key_secret))


def send_booking_confirmation_email(booking_id: int):
    from app.database import SessionLocal
    import os
    import tempfile

    db = SessionLocal()
    temp_path = None

    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id
        ).first()

        if not booking or booking.status != "Confirmed":
            return

        customer = db.query(User).filter(
            User.id == booking.customer_id
        ).first()

        if not customer or not getattr(customer, "email", None):
            return

        pdf_bytes = generate_ticket_pdf(db, booking_id)

        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            prefix="ticket_",
            delete=False,
        ) as pdf_file:
            pdf_file.write(pdf_bytes)
            temp_path = pdf_file.name

        send_email_notification(
            recipient=customer.email,
            subject="Booking Confirmed - {}".format(
                booking.booking_number or booking.id
            ),
            body=(
                "Your booking is confirmed!\n\n"
                "Booking number: {}\n"
                "Amount paid: INR {}\n\n"
                "Your PDF ticket is attached."
            ).format(
                booking.booking_number or booking.id,
                booking.grand_total,
            ),
            attachment_path=temp_path,
        )

    except Exception:
        logger.exception(
            "Confirmation email failed for booking %s",
            booking_id,
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        db.close()


def send_payment_failed_email(booking_id: int):
    from app.database import SessionLocal

    db = SessionLocal()

    try:
        booking = db.query(Booking).filter(
            Booking.id == booking_id
        ).first()

        if not booking:
            return

        customer = db.query(User).filter(
            User.id == booking.customer_id
        ).first()

        if not customer or not getattr(customer, "email", None):
            return

        send_email_notification(
            recipient=customer.email,
            subject="Payment Failed - Booking {}".format(
                booking.booking_number or booking.id
            ),
            body=(
                "Your payment for booking {} was unsuccessful.\n"
                "Please retry before the booking expires."
            ).format(booking.booking_number or booking.id),
        )

    except Exception:
        logger.exception(
            "Payment failure email failed for booking %s",
            booking_id,
        )
    finally:
        db.close()


def verify_seat_locks(booking):
    for booked_seat in booking.booked_seats:
        owner = redis_client.get(
            lock_key(booking.show_id, booked_seat.seat_id)
        )

        if isinstance(owner, bytes):
            owner = owner.decode("utf-8")

        if owner != str(booking.customer_id):
            return False

    return True


def confirm_booking(db, booking, payment, razorpay_payment_id):
    # Prevent duplicate ticket creation on repeated webhook delivery.
    if booking.status == "Confirmed":
        payment.status = "Success"
        payment.transaction_id = razorpay_payment_id
        db.commit()
        return True

    if not verify_seat_locks(booking):
        # Payment was captured, but the seats are no longer locked.
        # Attempt to refund instead of confirming unavailable seats.
        try:
            amount_paise = int(
                Decimal(str(payment.amount)) * 100
            )

            client = get_razorpay_client()
            client.payment.refund(
                razorpay_payment_id,
                {"amount": amount_paise},
            )

            payment.status = "Refunded"
            payment.transaction_id = razorpay_payment_id
            booking.status = "Cancelled"
            db.commit()

        except Exception:
            db.rollback()
            logger.exception(
                "Automatic refund failed for payment %s",
                razorpay_payment_id,
            )

        return False

    payment.status = "Success"
    payment.transaction_id = razorpay_payment_id
    payment.paid_at = datetime.utcnow()

    booking.status = "Confirmed"
    booking.confirmed_at = datetime.utcnow()

    existing_ticket = db.query(Ticket).filter(
        Ticket.booking_id == booking.id
    ).first()

    if not existing_ticket:
        for booked_seat in booking.booked_seats:
            db.add(
                Ticket(
                    booking_id=booking.id,
                    event_id=booking.event_id,
                    ticket_code="TKT-{}".format(
                        uuid4().hex[:12].upper()
                    ),
                    status="valid",
                )
            )

    db.commit()

    for booked_seat in booking.booked_seats:
        redis_client.delete(
            lock_key(booking.show_id, booked_seat.seat_id)
        )

    return True


async def notify_seats_booked(booking):
    await seat_ws_manager.broadcast(
        booking.show_id,
        {
            "event": "seats_booked",
            "show_id": booking.show_id,
            "seat_ids": [
                item.seat_id for item in booking.booked_seats
            ],
        },
    )


# 1. Create Razorpay order
@router.post("/bookings/{booking_id}/pay", status_code=201)
def create_payment_order(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = db.query(Booking).filter(
        Booking.id == booking_id
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if current_user.role != "Admin" and (
        booking.customer_id != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You cannot pay for this booking",
        )

    if booking.status == "Confirmed":
        raise HTTPException(
            status_code=409,
            detail="Booking is already confirmed",
        )

    if booking.status in ("Expired", "Cancelled"):
        raise HTTPException(
            status_code=400,
            detail="Booking is expired or cancelled",
        )

    if (
        booking.expires_at is None
        or booking.expires_at <= datetime.utcnow()
    ):
        booking.status = "Expired"
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Booking payment window has expired",
        )

    if not booking.grand_total or booking.grand_total <= 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid booking amount",
        )

    # Reuse an existing pending order if one exists.
    existing_payment = (
        db.query(Payment)
        .filter(
            Payment.booking_id == booking.id,
            Payment.status == "Pending",
        )
        .order_by(Payment.id.desc())
        .first()
    )

    if existing_payment and existing_payment.transaction_id.startswith("order_"):
        order_id = existing_payment.transaction_id

        return {
            "payment_id": existing_payment.id,
            "booking_id": booking.id,
            "razorpay_order_id": order_id,
            "amount": int(Decimal(str(booking.grand_total)) * 100),
            "currency": "INR",
            "key_id": os.getenv("RAZORPAY_KEY_ID"),
        }

    try:
        client = get_razorpay_client()

        amount_paise = int(
            Decimal(str(booking.grand_total)) * 100
        )

        order = client.order.create(
            data={
                "amount": amount_paise,
                "currency": "INR",
                "receipt": booking.booking_number or str(booking.id),
                "notes": {
                    "booking_id": str(booking.id),
                    "booking_number": booking.booking_number or "",
                },
            }
        )

        payment = Payment(
            booking_id=booking.id,
            transaction_id=order["id"],
            amount=booking.grand_total,
            payment_method="Razorpay",
            status="Pending",
        )

        db.add(payment)
        db.commit()
        db.refresh(payment)

        return {
            "payment_id": payment.id,
            "booking_id": booking.id,
            "razorpay_order_id": order["id"],
            "amount": amount_paise,
            "currency": "INR",
            "key_id": os.getenv("RAZORPAY_KEY_ID"),
        }

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Razorpay order creation failed")
        raise HTTPException(
            status_code=500,
            detail="Could not create Razorpay order",
        )


# 2. Verify Razorpay checkout payment
@router.post("/bookings/{booking_id}/verify")
async def verify_payment(
    booking_id: int,
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order_id = payload.get("razorpay_order_id")
    payment_id = payload.get("razorpay_payment_id")
    signature = payload.get("razorpay_signature")

    if not order_id or not payment_id or not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Razorpay verification details",
        )

    booking = db.query(Booking).filter(
        Booking.id == booking_id
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if current_user.role != "Admin" and (
        booking.customer_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    payment = db.query(Payment).filter(
        Payment.booking_id == booking.id,
        Payment.transaction_id == order_id,
    ).first()

    if not payment:
        raise HTTPException(
            status_code=404,
            detail="Payment order not found",
        )

    client = get_razorpay_client()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")

    expected_signature = hmac.new(
        key_secret.encode("utf-8"),
        "{}|{}".format(order_id, payment_id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(
            status_code=400,
            detail="Invalid Razorpay payment signature",
        )

    try:
        payment_details = client.payment.fetch(payment_id)

        if payment_details.get("order_id") != order_id:
            raise HTTPException(
                status_code=400,
                detail="Payment does not match this order",
            )

        if payment_details.get("status") == "authorized":
            client.payment.capture(
                payment_id,
                int(Decimal(str(payment.amount)) * 100),
            )
            payment_details = client.payment.fetch(payment_id)

        if payment_details.get("status") != "captured":
            raise HTTPException(
                status_code=400,
                detail="Razorpay payment has not been captured",
            )

        success = confirm_booking(
            db,
            booking,
            payment,
            payment_id,
        )

        if not success:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Seat lock expired. Payment refund was attempted; "
                    "check payment status."
                ),
            )

        background_tasks.add_task(
            send_booking_confirmation_email,
            booking.id,
        )

        await notify_seats_booked(booking)

        return {
            "message": "Payment verified successfully",
            "booking_id": booking.id,
            "payment_id": payment.id,
            "razorpay_payment_id": payment_id,
            "booking_status": booking.status,
            "payment_status": payment.status,
        }

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Razorpay payment verification failed")
        raise HTTPException(
            status_code=500,
            detail="Payment verification failed",
        )


# 3. Razorpay webhook
@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")

    if not signature or not webhook_secret:
        raise HTTPException(
            status_code=400,
            detail="Webhook signature configuration is missing",
        )

    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook signature",
        )

    try:
        event_data = await request.json()
        event = event_data.get("event")

        entity = (
            event_data.get("payload", {})
            .get("payment", {})
            .get("entity", {})
        )

        order_id = entity.get("order_id")
        payment_id = entity.get("id")

        if not order_id or not payment_id:
            return {"message": "Webhook received"}

        payment = db.query(Payment).filter(
            Payment.transaction_id == order_id
        ).first()

        # A repeated captured webhook is harmless.
        if not payment:
            payment = db.query(Payment).filter(
                Payment.transaction_id == payment_id
            ).first()

            if payment and payment.status == "Success":
                return {"message": "Payment already processed"}

        if not payment:
            return {"message": "Payment record not found"}

        booking = db.query(Booking).filter(
            Booking.id == payment.booking_id
        ).first()

        if not booking:
            return {"message": "Booking not found"}

        if event == "payment.captured":
            if payment.status == "Success":
                return {"message": "Payment already processed"}

            success = confirm_booking(
                db,
                booking,
                payment,
                payment_id,
            )

            if success:
                background_tasks.add_task(
                    send_booking_confirmation_email,
                    booking.id,
                )
                await notify_seats_booked(booking)

        elif event == "payment.failed":
            if payment.status not in ("Success", "Refunded"):
                payment.status = "Failed"
                db.commit()

                background_tasks.add_task(
                    send_payment_failed_email,
                    booking.id,
                )

        return {"message": "Webhook processed"}

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Razorpay webhook processing failed")
        raise HTTPException(
            status_code=500,
            detail="Webhook processing failed",
        )


# 4. List booking payments
@router.get("/bookings/{booking_id}/payments")
def list_booking_payments(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = db.query(Booking).filter(
        Booking.id == booking_id
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if current_user.role != "Admin" and (
        booking.customer_id != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You cannot view these payments",
        )

    payments = (
        db.query(Payment)
        .filter(Payment.booking_id == booking_id)
        .order_by(Payment.id.desc())
        .all()
    )

    return [
        {
            "id": item.id,
            "booking_id": item.booking_id,
            "transaction_id": item.transaction_id,
            "amount": item.amount,
            "payment_method": item.payment_method,
            "status": item.status,
            "paid_at": item.paid_at,
            "created_at": item.created_at,
        }
        for item in payments
    ]


# 5. Resend booking confirmation
@router.post("/bookings/{booking_id}/resend-confirmation")
def resend_booking_confirmation(
    booking_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = db.query(Booking).filter(
        Booking.id == booking_id
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if current_user.role != "Admin" and (
        booking.customer_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    if booking.status != "Confirmed":
        raise HTTPException(
            status_code=400,
            detail="Only confirmed bookings can receive confirmation emails",
        )

    background_tasks.add_task(
        send_booking_confirmation_email,
        booking.id,
    )

    return {
        "message": "Booking confirmation email queued",
        "booking_id": booking.id,
    }
