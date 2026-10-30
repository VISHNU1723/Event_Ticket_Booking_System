
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from fastapi import BackgroundTasks

from app.database import get_db
from app.auth.router import get_current_user
from app.models.user import User
from app.models.booking import Booking, BookedSeat
from app.models.show import Show, ShowSeatPrice
from app.models.event import Event
from app.models.venue import Seat
from app.schemas.booking import BookingCreate
from app.services.redis_client import redis_client
from app.services.seat_lock_service import lock_key
from app.models.refund import Refund
from app.services.cancellation_service import cancel_booking
from app.services.notification_service import send_email_notification
from app.services.dynamic_pricing import get_dynamic_price

router = APIRouter(prefix="/bookings", tags=["Bookings"])

CONVENIENCE_FEE_PER_TICKET = Decimal("30.00")
GST_RATE = Decimal("0.18")
MAX_SEATS_PER_BOOKING = 10


def money(value):
    return Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def serialize_booking(booking):
    return {
        "id": booking.id,
        "booking_number": booking.booking_number,
        "customer_id": booking.customer_id,
        "show_id": booking.show_id,
        "seat_count": booking.seat_count,
        "ticket_total": booking.ticket_total,
        "convenience_fee": booking.convenience_fee,
        "gst_amount": booking.gst_amount,
        "grand_total": booking.grand_total,
        "status": booking.status,
        "expires_at": booking.expires_at,
        "confirmed_at": booking.confirmed_at,
        "booked_seats": [
            {
                "seat_id": item.seat_id,
                "price": item.price,
            }
            for item in booking.booked_seats
        ],
    }


def can_view_booking(db, booking, user):
    if user.role == "Admin":
        return True

    if user.role == "Organizer":
        show = db.query(Show).filter(
            Show.id == booking.show_id
        ).first()

        if not show:
            return False

        event = db.query(Event).filter(
            Event.id == show.event_id
        ).first()

        return bool(event and event.organizer_id == user.id)

    return booking.customer_id == user.id


@router.post("", status_code=201)
def create_booking(
    payload: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Customer":
        raise HTTPException(
            status_code=403,
            detail="Only customers can create bookings",
        )

    if (
        not payload.seat_ids
        or len(payload.seat_ids) != len(set(payload.seat_ids))
    ):
        raise HTTPException(
            status_code=400,
            detail="Select unique seat IDs",
        )

    if len(payload.seat_ids) > MAX_SEATS_PER_BOOKING:
        raise HTTPException(
            status_code=400,
            detail="Maximum 10 seats per booking",
        )

    show = db.query(Show).filter(
        Show.id == payload.show_id
    ).first()

    if not show:
        raise HTTPException(
            status_code=404,
            detail="Show not found",
        )

    now = datetime.utcnow()

    if show.status != "Scheduled" or show.booking_closes_at <= now:
        raise HTTPException(
            status_code=400,
            detail="This show is not open for booking",
        )

    seats = (
        db.query(Seat)
        .filter(
            Seat.id.in_(payload.seat_ids),
            Seat.screen_id == show.screen_id,
            Seat.is_active.is_(True),
        )
        .all()
    )

    if len(seats) != len(payload.seat_ids):
        raise HTTPException(
            status_code=400,
            detail="One or more seats are invalid or unavailable",
        )

    lock_ttls = []

    for seat_id in payload.seat_ids:
        key = lock_key(show.id, seat_id)
        owner = redis_client.get(key)

        if owner != str(current_user.id):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Every selected seat must be locked "
                    "by your account before booking"
                ),
            )

        ttl = redis_client.ttl(key)

        if ttl <= 0:
            raise HTTPException(
                status_code=409,
                detail="A selected seat lock has expired",
            )

        lock_ttls.append(ttl)

    existing = (
        db.query(BookedSeat)
        .join(Booking, Booking.id == BookedSeat.booking_id)
        .filter(
            BookedSeat.show_id == show.id,
            BookedSeat.seat_id.in_(payload.seat_ids),
            Booking.status.in_(["Pending Payment", "Confirmed"]),
            Booking.expires_at > now,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="One or more seats already have an active booking",
        )

    prices = {
        item.category: Decimal(str(item.price))
        for item in db.query(ShowSeatPrice)
        .filter(ShowSeatPrice.show_id == show.id)
        .all()
    }

    seat_prices = []

    for seat in seats:
        original_price = prices.get(seat.category)

        price = (
           get_dynamic_price(db, show, original_price)
           if original_price is not None
           else None
        )

        if price is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No price configured for seat category "
                    "{}".format(seat.category)
                ),
            )

        seat_prices.append((seat.id, price))

    ticket_total = money(
        sum((price for _, price in seat_prices), Decimal("0.00"))
    )

    convenience_fee = money(
        CONVENIENCE_FEE_PER_TICKET * len(seat_prices)
    )

    gst_amount = money(
        (ticket_total + convenience_fee) * GST_RATE
    )

    grand_total = money(
        ticket_total + convenience_fee + gst_amount
    )

    expires_at = now + timedelta(seconds=min(lock_ttls))

    booking_number = "BKG-{}-{}".format(
        now.strftime("%Y%m%d"),
        uuid4().hex[:8].upper(),
    )

    booking = Booking(
        booking_number=booking_number,
        customer_id=current_user.id,
        show_id=show.id,
        seat_count=len(seat_prices),
        ticket_total=ticket_total,
        convenience_fee=convenience_fee,
        gst_amount=gst_amount,
        grand_total=grand_total,
        status="Pending Payment",
        expires_at=expires_at,

        # Keep these only while the legacy database columns
        # user_id, event_id and quantity remain NOT NULL.
        user_id=current_user.id,
        event_id=show.event_id,
        quantity=len(seat_prices),
    )

    for seat_id, price in seat_prices:
        booking.booked_seats.append(
            BookedSeat(
                show_id=show.id,
                seat_id=seat_id,
                price=price,
            )
        )

    try:
        db.add(booking)
        db.commit()
        db.refresh(booking)
    except Exception:
        db.rollback()
        raise

    return serialize_booking(booking)


@router.get("")
def list_bookings(
    status: Optional[str] = None,
    show_id: Optional[int] = Query(None, gt=0),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if skip < 0:
        raise HTTPException(status_code=400, detail="skip must be 0 or greater")
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date must be before or equal to to_date",
        )

    query = db.query(Booking)

    # Restrict results to bookings the current user is allowed to see.
    if current_user.role == "Admin":
        pass
    elif current_user.role == "Organizer":
        query = (
            query.join(Show, Show.id == Booking.show_id)
            .join(Event, Event.id == Show.event_id)
            .filter(Event.organizer_id == current_user.id)
        )
    else:
        query = query.filter(Booking.customer_id == current_user.id)

    if status:
        query = query.filter(Booking.status == status)
    if show_id is not None:
        query = query.filter(Booking.show_id == show_id)
    if from_date:
        query = query.filter(Booking.created_at >= from_date)
    if to_date:
        query = query.filter(Booking.created_at <= to_date)

    total = query.count()
    bookings = (
        query.options(joinedload(Booking.booked_seats))
        .order_by(Booking.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "items": [serialize_booking(booking) for booking in bookings],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/{booking_id}")
def get_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = (
        db.query(Booking)
        .options(joinedload(Booking.booked_seats))
        .filter(Booking.id == booking_id)
        .first()
    )

    if not booking:
        raise HTTPException(
            status_code=404,
            detail="Booking not found",
        )

    if not can_view_booking(db, booking, current_user):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view this booking",
        )

    return serialize_booking(booking)



@router.put("/{booking_id}/cancel")
def cancel_booking_endpoint(
    booking_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = (
        db.query(Booking)
        .filter(Booking.id == booking_id)
        .first()
    )

    if not booking:
        raise HTTPException(
            status_code=404,
            detail="Booking not found",
        )

    # Preserve the existing cancellation and refund logic.
    result = cancel_booking(
        db,
        booking,
        current_user,
        background_tasks=background_tasks,
    )

    customer = (
        db.query(User)
        .filter(User.id == booking.customer_id)
        .first()
    )

    if customer and getattr(customer, "email", None):
        background_tasks.add_task(
            send_email_notification,
            recipient=customer.email,
            subject="Booking Cancelled - Refund Details",
            body=(
                "Your booking has been cancelled.\n\n"
                "Booking number: {}\n"
                "Booking ID: {}\n"
                "Refund amount: INR {}\n"
                "Refund percentage: {}%\n"
                "Refund status: {}\n\n"
                "Please note that the refund processing in this project "
                "is simulated."
            ).format(
                booking.booking_number or booking.id,
                booking.id,
                result["refund_amount"],
                result["refund_percentage"],
                result["refund_status"],
            ),
        )

    return result


@router.get("/{booking_id}/refunds")
def get_booking_refunds(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = (
        db.query(Booking)
        .filter(Booking.id == booking_id)
        .first()
    )

    if not booking:
        raise HTTPException(
            status_code=404,
            detail="Booking not found",
        )

    if not can_view_booking(db, booking, current_user):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view these refunds",
        )

    refunds = (
        db.query(Refund)
        .filter(Refund.booking_id == booking_id)
        .order_by(Refund.id.desc())
        .all()
    )

    return [
        {
            "id": refund.id,
            "booking_id": refund.booking_id,
            "payment_id": refund.payment_id,
            "amount": refund.amount,
            "reason": refund.reason,
            "status": refund.status,
            "refunded_at": refund.refunded_at,
            "created_at": refund.created_at,
        }
        for refund in refunds
    ]
