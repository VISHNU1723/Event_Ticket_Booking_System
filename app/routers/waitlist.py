
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.router import get_current_user
from app.database import get_db
from app.models.booking import Booking, BookedSeat
from app.models.show import Show
from app.models.venue import Seat
from app.models.user import User
from app.models.waitlist import Waitlist

router = APIRouter(tags=["Waitlist"])


class WaitlistCreate(BaseModel):
    seat_count: int = Field(..., gt=0)
    preferred_category: str = Field(..., min_length=1, max_length=50)


@router.post("/shows/{show_id}/waitlist", status_code=201)
def join_waitlist(
    show_id: int,
    payload: WaitlistCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Customer":
        raise HTTPException(status_code=403, detail="Only customers can join the waitlist")

    show = db.query(Show).filter(Show.id == show_id).first()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    if hasattr(show, "status") and show.status != "Scheduled":
        raise HTTPException(status_code=400, detail="Waitlist is available only for scheduled shows")

    available_seats = (
        db.query(Seat)
        .filter(Seat.screen_id == show.screen_id, Seat.is_active.is_(True))
        .count()
    )

    already_booked = (
        db.query(Booking)
        .filter(
            Booking.show_id == show_id,
            Booking.customer_id == current_user.id,
            Booking.status == "Confirmed",
        )
        .first()
    )

    booked_count = (
        db.query(BookedSeat)
        .join(Booking, Booking.id == BookedSeat.booking_id)
        .filter(Booking.show_id == show_id, Booking.status == "Confirmed")
        .count()
    )

    if available_seats - booked_count > 0:
        raise HTTPException(status_code=400, detail="Waitlist is available only when the show is sold out")

    if already_booked:
        raise HTTPException(status_code=400, detail="You have already booked this show")

    existing = (
        db.query(Waitlist)
        .filter(
            Waitlist.show_id == show_id,
            Waitlist.customer_id == current_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="You have already joined this show's waitlist")

    entry = Waitlist(
        show_id=show_id,
        customer_id=current_user.id,
        seat_count=payload.seat_count,
        preferred_category=payload.preferred_category.strip(),
        status="Waiting",
    )

    db.add(entry)
    try:
        db.commit()
        db.refresh(entry)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not join waitlist")

    return {
        "message": "Added to waitlist",
        "waitlist_id": entry.id,
        "show_id": entry.show_id,
        "seat_count": entry.seat_count,
        "preferred_category": entry.preferred_category,
        "status": entry.status,
        "created_at": entry.created_at,
    }


@router.get("/shows/{show_id}/waitlist")
def get_show_waitlist(
    show_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("Admin", "Organizer"):
        raise HTTPException(status_code=403, detail="Only Admin or Organizer can view the waitlist")

    show = db.query(Show).filter(Show.id == show_id).first()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    query = db.query(Waitlist).filter(Waitlist.show_id == show_id)
    total = query.count()

    entries = (
        query.order_by(Waitlist.created_at.asc(), Waitlist.id.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "items": [
            {
                "waitlist_id": entry.id,
                "customer_id": entry.customer_id,
                "show_id": entry.show_id,
                "seat_count": entry.seat_count,
                "preferred_category": entry.preferred_category,
                "status": entry.status,
                "created_at": entry.created_at,
                "notified_at": entry.notified_at,
            }
            for entry in entries
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.delete("/waitlist/{waitlist_id}")
def leave_waitlist(
    waitlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = db.query(Waitlist).filter(Waitlist.id == waitlist_id).first()

    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")

    if current_user.role != "Admin" and entry.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can remove only your own waitlist entry")

    db.delete(entry)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not remove waitlist entry")

    return {"message": "Removed from waitlist", "waitlist_id": waitlist_id}
