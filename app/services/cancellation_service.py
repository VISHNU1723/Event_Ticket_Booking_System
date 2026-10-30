
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookedSeat
from app.models.refund import Refund
from app.models.payment import Payment
from app.models.show import Show
from app.models.waitlist import Waitlist
from app.models.user import User
from app.services.redis_client import redis_client
from app.services.seat_lock_service import lock_key
from app.services.notification_service import send_email_notification
from app.websockets.manager import seat_ws_manager


def money(value):
    return Decimal(str(value)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def cancel_booking(
    db: Session,
    booking: Booking,
    user,
    background_tasks: BackgroundTasks = None,
):
    if user.role != "Admin" and booking.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if booking.status != "Confirmed":
        raise HTTPException(
            status_code=400,
            detail="Only confirmed bookings can be cancelled",
        )

    show = db.query(Show).filter(Show.id == booking.show_id).first()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    now = datetime.utcnow()
    show_time = show.start_time

    if show_time <= now:
        raise HTTPException(
            status_code=400,
            detail="Cancellation is not allowed after the show starts",
        )

    hours_left = (show_time - now).total_seconds() / 3600

    if hours_left > 24:
        refund_percentage = Decimal("1.00")
    elif hours_left >= 2:
        refund_percentage = Decimal("0.50")
    else:
        raise HTTPException(
            status_code=400,
            detail="Cancellation is not allowed less than 2 hours before the show",
        )

    refund_amount = money(booking.ticket_total * refund_percentage)

    payment = (
        db.query(Payment)
        .filter(Payment.booking_id == booking.id)
        .order_by(Payment.id.desc())
        .first()
    )

    try:
        refund = Refund(
            booking_id=booking.id,
            payment_id=payment.id if payment else None,
            amount=refund_amount,
            reason="Customer Cancellation",
            status="Refunded",
            refunded_at=now,
        )
        db.add(refund)

        booking.status = "Cancelled"

        if payment:
            payment.status = "Refunded"

        booked_seats = (
            db.query(BookedSeat)
            .filter(BookedSeat.booking_id == booking.id)
            .all()
        )

        for booked_seat in booked_seats:
            redis_client.delete(
                lock_key(show.id, booked_seat.seat_id)
            )

        db.commit()
        db.refresh(refund)

    except Exception:
        db.rollback()
        raise

    # Notify connected clients that seats have been released.
    import asyncio

    try:
        asyncio.run(
            seat_ws_manager.broadcast(
                show.id,
                {
                    "event": "seats_released",
                    "show_id": show.id,
                    "seat_ids": [
                        item.seat_id for item in booked_seats
                    ],
                    "reason": "Customer Cancellation",
                },
            )
        )
    except RuntimeError:
        pass
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Failed to broadcast released seats for show %s",
            show.id,
        )

    # Notify waitlisted customers when seats are released.
    waiting_entries = (
        db.query(Waitlist)
        .filter(
            Waitlist.show_id == show.id,
            Waitlist.status == "Waiting",
        )
        .order_by(
            Waitlist.created_at.asc(),
            Waitlist.id.asc(),
        )
        .all()
    )

    notified = []

    for entry in waiting_entries:
        customer = (
            db.query(User)
            .filter(User.id == entry.customer_id)
            .first()
        )

        if customer and getattr(customer, "email", None):
            email_body = (
                "Seats may now be available for your waitlisted show.\n\n"
                "Show ID: {}\n"
                "Requested seats: {}\n"
                "Preferred category: {}\n\n"
                "Please visit the booking platform to check availability."
            ).format(
                show.id,
                entry.seat_count,
                entry.preferred_category,
            )

            if background_tasks is not None:
                background_tasks.add_task(
                    send_email_notification,
                    recipient=customer.email,
                    subject="Seats May Be Available",
                    body=email_body,
                )
            else:
                # Compatibility for callers outside FastAPI endpoints.
                send_email_notification(
                    recipient=customer.email,
                    subject="Seats May Be Available",
                    body=email_body,
                )

        entry.status = "Notified"
        entry.notified_at = now
        notified.append(entry.customer_id)

    if waiting_entries:
        db.commit()

    return {
        "message": "Booking cancelled",
        "booking_id": booking.id,
        "booking_status": booking.status,
        "refund_amount": str(refund_amount),
        "refund_percentage": int(refund_percentage * 100),
        "refund_status": refund.status,
        "waitlisted_customers_notified": notified,
        "note": (
            "Refund status is recorded in the database. "
            "Verify your payment gateway integration for real refunds. "
            "Waitlist emails are queued when BackgroundTasks is provided."
        ),
    }
