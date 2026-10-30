
from datetime import datetime, timedelta
from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.show import Show
from app.models.venue import Seat
from app.services.redis_client import redis_client
from app.websockets.manager import seat_ws_manager


LOCK_TTL_SECONDS = 600
MAX_SEATS_PER_CUSTOMER = 10


def lock_key(show_id: int, seat_id: int) -> str:
    return "lock:show:{}:seat:{}".format(show_id, seat_id)


async def lock_seats(
    db: Session,
    show_id: int,
    seat_ids: List[int],
    user_id: int,
):
    if not seat_ids:
        raise HTTPException(status_code=400, detail="Select at least one seat")

    if len(seat_ids) != len(set(seat_ids)):
        raise HTTPException(
            status_code=400,
            detail="Duplicate seat IDs are not allowed",
        )

    if len(seat_ids) > MAX_SEATS_PER_CUSTOMER:
        raise HTTPException(
            status_code=400,
            detail="Maximum 10 seats per show",
        )

    show = db.query(Show).filter(Show.id == show_id).first()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    now = datetime.utcnow()

    if show.status != "Scheduled":
        raise HTTPException(
            status_code=400,
            detail="Show is not available for booking",
        )

    if show.booking_closes_at <= now:
        raise HTTPException(
            status_code=400,
            detail="Booking is closed for this show",
        )

    seats = (
        db.query(Seat)
        .filter(
            Seat.id.in_(seat_ids),
            Seat.screen_id == show.screen_id,
        )
        .all()
    )

    if len(seats) != len(seat_ids):
        raise HTTPException(
            status_code=400,
            detail="One or more seats do not belong to this show's screen",
        )

    unavailable = []

    for seat in seats:
        if not seat.is_active:
            unavailable.append(seat.id)
            continue

        if redis_client.exists(lock_key(show_id, seat.id)):
            unavailable.append(seat.id)

    if unavailable:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Some seats are unavailable",
                "seat_ids": unavailable,
            },
        )

    acquired = []

    try:
        for seat_id in seat_ids:
            key = lock_key(show_id, seat_id)

            success = redis_client.set(
                key,
                str(user_id),
                nx=True,
                ex=LOCK_TTL_SECONDS,
            )

            if not success:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Seat is already locked",
                        "seat_ids": [seat_id],
                    },
                )

            acquired.append(key)

    except Exception:
        # Roll back only locks acquired by this request.
        for key in acquired:
            owner = redis_client.get(key)
            if owner is not None and owner == str(user_id):
                redis_client.delete(key)
        raise

    expires_at = now + timedelta(seconds=LOCK_TTL_SECONDS)

    result = {
        "show_id": show_id,
        "seat_ids": seat_ids,
        "status": "Locked",
        "expires_at": expires_at.isoformat(),
        "message": "Seats locked for 10 minutes",
    }

    await seat_ws_manager.broadcast(
        show_id,
        {
            "event": "seats_locked",
            "show_id": show_id,
            "seat_ids": seat_ids,
            "user_id": user_id,
            "status": "Locked",
            "expires_at": expires_at.isoformat(),
        },
    )

    return result


async def release_seat_locks(
    show_id: int,
    seat_ids: List[int],
    user_id: int,
):
    released = []
    not_owned = []

    for seat_id in seat_ids:
        key = lock_key(show_id, seat_id)
        owner = redis_client.get(key)

        if owner is None:
            continue

        if owner == str(user_id):
            redis_client.delete(key)
            released.append(seat_id)
        else:
            not_owned.append(seat_id)

    if released:
        await seat_ws_manager.broadcast(
            show_id,
            {
                "event": "seats_released",
                "show_id": show_id,
                "seat_ids": released,
                "user_id": user_id,
                "status": "Available",
            },
        )

    if not_owned:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "You can release only your own seat locks",
                "seat_ids": not_owned,
                "released_seat_ids": released,
            },
        )

    return {
        "show_id": show_id,
        "released_seat_ids": released,
        "message": "Your seat locks have been released",
    }
