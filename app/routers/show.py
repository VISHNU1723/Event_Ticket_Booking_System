
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.database import get_db
from app.models.event import Event
from app.models.show import Show, ShowSeatPrice
from app.models.venue import Screen, Seat
from app.models.user import User
from app.auth.router import get_current_user
from app.schemas.seat_lock import SeatLockRequest
from app.services.seat_lock_service import lock_seats, release_seat_locks
from app.services.redis_client import redis_client
from app.websockets.manager import seat_ws_manager
from app.models.booking import Booking
from app.services.notification_service import send_email_notification
from app.services.dynamic_pricing import get_dynamic_price

router = APIRouter(tags=["Shows"])


class SeatPriceInput(BaseModel):
    category: str
    price: int = Field(..., gt=0)


class ShowCreate(BaseModel):
    screen_id: int
    show_date: datetime
    start_time: datetime
    category_prices: List[SeatPriceInput]


class ShowUpdate(BaseModel):
    screen_id: Optional[int] = None
    show_date: Optional[datetime] = None
    start_time: Optional[datetime] = None
    status: Optional[str] = None
    category_prices: Optional[List[SeatPriceInput]] = None


def require_organizer(user: User):
    if (
        user.role != "Organizer"
        or not user.is_active
        or not user.is_approved
    ):
        raise HTTPException(
            status_code=403,
            detail="Only approved, active organizers can manage shows",
        )


def get_owned_event(db: Session, event_id: int, user: User) -> Event:
    event = db.query(Event).filter(Event.id == event_id).first()

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if event.organizer_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="You can manage only your own events",
        )

    return event


def validate_prices(db: Session, screen_id: int, prices: List[SeatPriceInput]):
    allowed_categories = {"Silver", "Gold", "Recliner"}

    if not prices:
        raise HTTPException(
            status_code=400,
            detail="Provide prices for every seat category",
        )

    categories = [
        item.get("category") if isinstance(item, dict) else item.category
        for item in prices
    ]

    if len(categories) != len(set(categories)):
        raise HTTPException(
            status_code=400,
            detail="Duplicate seat price categories are not allowed",
        )

    if not set(categories).issubset(allowed_categories):
        raise HTTPException(
            status_code=400,
            detail="Categories must be Silver, Gold, or Recliner",
        )

    screen_seats = (
        db.query(Seat)
        .filter(Seat.screen_id == screen_id, Seat.is_active == True)
        .all()
    )

    required_categories = set(seat.category for seat in screen_seats)

    if not required_categories:
        raise HTTPException(
            status_code=400,
            detail="The screen has no active seats",
        )

    if not required_categories.issubset(set(categories)):
        raise HTTPException(
            status_code=400,
            detail="Provide a price for every seat category on this screen",
        )


def check_screen(db: Session, screen_id: int, venue_id: int):
    screen = db.query(Screen).filter(Screen.id == screen_id).first()

    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")

    if screen.venue_id != venue_id:
        raise HTTPException(
            status_code=400,
            detail="Screen does not belong to this event's venue",
        )

    return screen


def check_schedule(
    db: Session,
    screen_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_show_id: Optional[int] = None,
):
    if start_time <= datetime.now():
        raise HTTPException(
            status_code=400,
            detail="Shows must be scheduled for a future time",
        )

    existing_shows = (
        db.query(Show)
        .filter(
            Show.screen_id == screen_id,
            Show.status == "Scheduled",
        )
        .all()
    )

    for existing in existing_shows:
        if existing.id == exclude_show_id:
            continue

        earliest_allowed_start = existing.end_time + timedelta(minutes=15)
        latest_allowed_end = start_time - timedelta(minutes=15)

        overlaps = (
            start_time < earliest_allowed_start
            and end_time > existing.start_time
        )

        too_close_before = (
            start_time >= existing.start_time
            and start_time < earliest_allowed_start
        )

        too_close_after = (
            end_time <= existing.start_time
            and end_time > latest_allowed_end
        )

        if overlaps or too_close_before or too_close_after:
            raise HTTPException(
                status_code=400,
                detail="Shows on the same screen require a 15-minute cleaning gap",
            )


def serialize_show(db: Session, show: Show):
    return {
        "id": show.id,
        "event_id": show.event_id,
        "screen_id": show.screen_id,
        "show_date": show.show_date,
        "start_time": show.start_time,
        "end_time": show.end_time,
        "booking_closes_at": show.booking_closes_at,
        "status": show.status,
        "category_prices": [
            {"category": price.category, "price": price.price}
            for price in show.category_prices
        ],
    }


@router.post("/events/{event_id}/shows", status_code=201)
def create_show(
    event_id: int,
    payload: ShowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_organizer(current_user)

    if payload.show_date.date() < datetime.now().date():
        raise HTTPException(
            status_code=400,
            detail="Show date cannot be in the past",
        )

    event = get_owned_event(db, event_id, current_user)

    if event.status != "Published":
        raise HTTPException(
            status_code=400,
            detail="Shows can only be created for published events",
        )

    check_screen(db, payload.screen_id, event.venue_id)
    validate_prices(db, payload.screen_id, payload.category_prices)

    end_time = payload.start_time + timedelta(
        minutes=event.duration_minutes
    )

    check_schedule(db, payload.screen_id, payload.start_time, end_time)

    show = Show(
        event_id=event.id,
        screen_id=payload.screen_id,
        show_date=payload.show_date,
        start_time=payload.start_time,
        end_time=end_time,
        booking_closes_at=payload.start_time - timedelta(minutes=30),
        status="Scheduled",
    )

    for item in payload.category_prices:
        show.category_prices.append(
            ShowSeatPrice(category=item.category, price=item.price)
        )

    db.add(show)
    db.commit()
    db.refresh(show)

    from app.routers.event import invalidate_event_cache
    invalidate_event_cache(show.event_id)

    return serialize_show(db, show)


@router.get("/events/{event_id}/shows")
def list_event_shows(
    event_id: int,
    db: Session = Depends(get_db),
):
    event = db.query(Event).filter(Event.id == event_id).first()

    if not event or event.status != "Published":
        raise HTTPException(
            status_code=404,
            detail="Published event not found",
        )

    shows = (
        db.query(Show)
        .filter(
            Show.event_id == event_id,
            Show.status == "Scheduled",
        )
        .order_by(Show.start_time)
        .all()
    )

    return [serialize_show(db, show) for show in shows]


@router.put("/shows/{show_id}")
def update_show(
    show_id: int,
    payload: ShowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_organizer(current_user)

    show = db.query(Show).filter(Show.id == show_id).first()

    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    event = get_owned_event(db, show.event_id, current_user)
    changes = payload.dict(exclude_unset=True)

    if "show_date" in changes and changes["show_date"].date() < datetime.now().date():
        raise HTTPException(
            status_code=400,
            detail="Show date cannot be in the past",
        )

    if "status" in changes and changes["status"] not in ["Scheduled", "Cancelled"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid show status",
        )

    screen_id = changes.get("screen_id", show.screen_id)
    start_time = changes.get("start_time", show.start_time)

    check_screen(db, screen_id, event.venue_id)

    end_time = start_time + timedelta(minutes=event.duration_minutes)

    check_schedule(
        db,
        screen_id,
        start_time,
        end_time,
        exclude_show_id=show.id,
    )

    if "category_prices" in changes:
        if db.query(ShowSeatPrice).filter(
            ShowSeatPrice.show_id == show.id
        ).count():
            from app.models.booking import Booking

            booking_exists = (
                db.query(Booking)
                .filter(
                    Booking.event_id == event.id,
                    Booking.status == "confirmed",
                )
                .first()
            )

            if booking_exists:
                raise HTTPException(
                    status_code=400,
                    detail="Prices cannot change after a confirmed booking",
                )

        validate_prices(db, screen_id, changes["category_prices"])

        db.query(ShowSeatPrice).filter(
            ShowSeatPrice.show_id == show.id
        ).delete(synchronize_session=False)

        for item in changes["category_prices"]:
            show.category_prices.append(
                ShowSeatPrice(
                    category=(
                        item.get("category")
                        if isinstance(item, dict)
                        else item.category
                    ),
                    price=(
                        item.get("price")
                        if isinstance(item, dict)
                        else item.price
                    )
                )
            )

    show.screen_id = screen_id
    show.start_time = start_time
    show.end_time = end_time
    show.booking_closes_at = start_time - timedelta(minutes=30)

    if "show_date" in changes:
        show.show_date = changes["show_date"]

    if "status" in changes:
        show.status = changes["status"]

    db.commit()
    db.refresh(show)

    from app.routers.event import invalidate_event_cache
    invalidate_event_cache(show.event_id)

    return serialize_show(db, show)



@router.put("/shows/{show_id}/cancel")
async def cancel_show(
    show_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_organizer(current_user)

    show = db.query(Show).filter(Show.id == show_id).first()

    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    get_owned_event(db, show.event_id, current_user)

    if show.status == "Cancelled":
        raise HTTPException(
            status_code=400,
            detail="Show is already cancelled",
        )

    # Find confirmed bookings before changing the show status.
    bookings = (
        db.query(Booking)
        .filter(
            Booking.show_id == show.id,
            Booking.status == "Confirmed",
        )
        .all()
    )

    event = db.query(Event).filter(Event.id == show.event_id).first()
    event_title = event.title if event else "Your event"

    recipients = set()
    for booking in bookings:
        customer = (
            db.query(User)
            .filter(User.id == booking.customer_id)
            .first()
        )
        if customer and getattr(customer, "email", None):
            recipients.add(customer.email)

    show.status = "Cancelled"
    db.commit()
    db.refresh(show)

    from app.routers.event import invalidate_event_cache
    invalidate_event_cache(show.event_id)

    await seat_ws_manager.broadcast(
        show.id,
        {
            "event": "show_cancelled",
            "show_id": show.id,
            "status": show.status,
            "message": "This show has been cancelled",
        },
    )

    # Queue one email per unique customer.
    for email in recipients:
        background_tasks.add_task(
            send_email_notification,
            recipient=email,
            subject="Show Cancelled - {}".format(event_title),
            body=(
                "We are sorry to inform you that this show has been cancelled.\n\n"
                "Event: {}\n"
                "Show ID: {}\n"
                "Start time: {}\n\n"
                "Please contact the event organizer regarding booking and refund arrangements."
            ).format(event_title, show.id, show.start_time),
        )

    return {
        "message": "Show cancelled successfully",
        "show_id": show.id,
        "status": show.status,
        "customer_emails_queued": len(recipients),
    }



@router.get("/{show_id}/seats")
def get_show_seats(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    show = db.query(Show).filter(Show.id == show_id).first()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    seats = (
        db.query(Seat)
        .filter(Seat.screen_id == show.screen_id)
        .order_by(Seat.row_label, Seat.seat_number)
        .all()
    )

    result = []
    for seat in seats:
        lock_key = "lock:show:{}:seat:{}".format(show_id, seat.id)
        lock_owner = redis_client.get(lock_key)

        price_record = (
            db.query(ShowSeatPrice)
            .filter(
                ShowSeatPrice.show_id == show_id,
                ShowSeatPrice.category == seat.category,
            )
            .first()
        )

        if not seat.is_active:
            status = "Unavailable"
        elif lock_owner:
            owner_id = (
                lock_owner.decode("utf-8")
                if isinstance(lock_owner, bytes)
                else str(lock_owner)
            )
            status = "Yours" if owner_id == str(current_user.id) else "Locked"
        else:
            status = "Available"

        result.append({
            "seat_id": seat.id,
            "row": seat.row_label,
            "seat_number": seat.seat_number,
            "category": seat.category,
            "price": (
                get_dynamic_price(db, show, price_record.price)
                if price_record else None
            ),
            "status": status,
        })

    return {"show_id": show_id, "seats": result}


@router.post("/{show_id}/lock-seats")
async def post_lock_seats(
    show_id: int,
    payload: SeatLockRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Allow a maximum of 5 seat-lock requests per customer per 60 seconds.
    key = f"rate_limit:seat_lock:{current_user.id}"

    try:
        attempts = redis_client.incr(key)

        if attempts == 1:
            redis_client.expire(key, 60)

        if attempts > 5:
            retry_after = max(redis_client.ttl(key), 1)

            raise HTTPException(
                status_code=429,
                detail={
                    "message": "Too many seat-lock requests. Try again later.",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

    except HTTPException:
        raise
    except Exception:
        import logging
        logging.exception("Redis seat-lock rate limiter failed")
        raise HTTPException(
            status_code=503,
            detail="Seat locking temporarily unavailable because rate limiting is unavailable",
        )

    return await lock_seats(
        db=db,
        show_id=show_id,
        seat_ids=payload.seat_ids,
        user_id=current_user.id,
    )



@router.delete("/{show_id}/lock-seats")
async def delete_lock_seats(
    show_id: int,
    payload: SeatLockRequest,
    current_user: User = Depends(get_current_user),
):
    return await release_seat_locks(
        show_id=show_id,
        seat_ids=payload.seat_ids,
        user_id=current_user.id,
    )