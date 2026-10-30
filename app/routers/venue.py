
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.venue import Venue, Screen, Seat
from app.auth.router import get_current_user

router = APIRouter(tags=["Venues, Screens & Seats"])


def require_admin(user=Depends(get_current_user)):
    if user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )
    return user


class VenueCreate(BaseModel):
    name: str
    city: str
    address: str
    is_active: bool = True


class VenueUpdate(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None


class ScreenCreate(BaseModel):
    name: str
    total_seats: int = Field(default=0, ge=0)


class SeatBulkCreate(BaseModel):
    rows: List[str] = Field(..., min_items=1)
    seats_per_row: int = Field(..., gt=0)
    category: Literal["Silver", "Gold", "Recliner"] = "Silver"


class SeatStatusUpdate(BaseModel):
    is_active: bool


@router.post("/venues", status_code=status.HTTP_201_CREATED)
def create_venue(
    data: VenueCreate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    venue = Venue(**data.dict())
    db.add(venue)
    try:
        db.commit()
        db.refresh(venue)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not create venue")
    return venue


@router.get("/venues")
def list_venues(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    city: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Venue)

    if city:
        query = query.filter(Venue.city.ilike("%{}%".format(city.strip())))

    total = query.count()
    items = query.order_by(Venue.id).offset(skip).limit(limit).all()

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.put("/venues/{venue_id}")
def update_venue(
    venue_id: int,
    data: VenueUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    venue = db.query(Venue).filter(Venue.id == venue_id).first()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    for key, value in data.dict(exclude_unset=True).items():
        setattr(venue, key, value)

    try:
        db.commit()
        db.refresh(venue)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not update venue")
    return venue


@router.post("/venues/{venue_id}/screens", status_code=status.HTTP_201_CREATED)
def create_screen(
    venue_id: int,
    data: ScreenCreate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    venue = db.query(Venue).filter(Venue.id == venue_id).first()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    screen = Screen(
        venue_id=venue_id,
        name=data.name,
        total_seats=data.total_seats,
    )
    db.add(screen)
    try:
        db.commit()
        db.refresh(screen)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not create screen")
    return screen


@router.post("/screens/{screen_id}/seats/bulk", status_code=status.HTTP_201_CREATED)
def create_seats_bulk(
    screen_id: int,
    data: SeatBulkCreate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    screen = db.query(Screen).filter(Screen.id == screen_id).first()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")

    rows = [row.strip().upper() for row in data.rows]
    if any(not row for row in rows) or len(set(rows)) != len(rows):
        raise HTTPException(status_code=400, detail="Rows must be non-empty and unique")

    existing = db.query(Seat).filter(Seat.screen_id == screen_id).all()
    existing_keys = {(seat.row_label, seat.seat_number) for seat in existing}
    seats = []

    for row in rows:
        for number in range(1, data.seats_per_row + 1):
            if (row, number) in existing_keys:
                raise HTTPException(
                    status_code=409,
                    detail="Seat {}{} already exists".format(row, number),
                )
            seats.append(
                Seat(
                    screen_id=screen_id,
                    row_label=row,
                    seat_number=number,
                    category=data.category,
                    is_active=True,
                )
            )

    db.add_all(seats)
    screen.total_seats = len(existing) + len(seats)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not create seats")

    return {
        "message": "Seats created successfully",
        "screen_id": screen_id,
        "created_count": len(seats),
        "total_seats": screen.total_seats,
    }


@router.get("/screens/{screen_id}/layout")
def get_screen_layout(
    screen_id: int,
    db: Session = Depends(get_db),
):
    screen = db.query(Screen).filter(Screen.id == screen_id).first()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")

    seats = (
        db.query(Seat)
        .filter(Seat.screen_id == screen_id)
        .order_by(Seat.row_label, Seat.seat_number)
        .all()
    )

    grouped = {}
    for seat in seats:
        grouped.setdefault(seat.row_label, []).append({
            "id": seat.id,
            "seat_number": seat.seat_number,
            "category": seat.category,
            "is_active": seat.is_active,
            "available": seat.is_active,
        })

    return {
        "screen_id": screen.id,
        "screen_name": screen.name,
        "total_seats": screen.total_seats,
        "rows": [
            {"row_label": row, "seats": row_seats}
            for row, row_seats in grouped.items()
        ],
    }


@router.put("/seats/{seat_id}/status")
def update_seat_status(
    seat_id: int,
    data: SeatStatusUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    seat = db.query(Seat).filter(Seat.id == seat_id).first()
    if not seat:
        raise HTTPException(status_code=404, detail="Seat not found")

    seat.is_active = data.is_active
    try:
        db.commit()
        db.refresh(seat)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not update seat status")

    return {
        "message": "Seat status updated successfully",
        "seat_id": seat.id,
        "is_active": seat.is_active,
    }
