
from datetime import datetime, date, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.router import get_current_user
from app.models.user import User
from app.models.event import Event
from app.models.show import Show
from app.models.booking import Booking, BookedSeat
from app.models.refund import Refund
from app.models.ticket import Ticket
from app.models.venue import Seat


router = APIRouter(prefix="/reports", tags=["Reports"])


def check_admin(user: User):
    if user.role != "Admin" or not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )


def check_report_access(user: User):
    if user.role == "Admin":
        return

    if (
        user.role != "Organizer"
        or not user.is_active
        or not user.is_approved
    ):
        raise HTTPException(
            status_code=403,
            detail="Admin or approved organizer access required",
        )


def apply_event_access(query, user: User):
    if user.role == "Organizer":
        query = query.filter(Event.organizer_id == user.id)
    return query


@router.get("/admin-dashboard")
def admin_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_admin(current_user)

    today = date.today()
    start = datetime.combine(today, time.min)
    end = start + timedelta(days=1)

    today_bookings = db.query(Booking).filter(
        Booking.created_at >= start,
        Booking.created_at < end,
    )

    today_revenue = db.query(
        func.coalesce(func.sum(Booking.grand_total), 0)
    ).filter(
        Booking.created_at >= start,
        Booking.created_at < end,
        func.lower(Booking.status) == "confirmed",
    ).scalar()

    today_refunds = db.query(
        func.coalesce(func.sum(Refund.amount), 0)
    ).filter(
        Refund.created_at >= start,
        Refund.created_at < end,
    ).scalar()

    active_events = db.query(Event).filter(
        Event.status == "Published"
    ).count()

    tickets_scanned = db.query(Ticket).filter(
        Ticket.scanned_at >= start,
        Ticket.scanned_at < end,
    ).count()

    return {
        "date": str(today),
        "today_bookings": today_bookings.count(),
        "today_revenue": float(today_revenue or 0),
        "today_refunds": float(today_refunds or 0),
        "active_events": active_events,
        "tickets_scanned_today": tickets_scanned,
    }



@router.get("/event-sales")
def event_sales_report(
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_report_access(current_user)

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date must be before or equal to to_date",
        )

    # Aggregate refunds separately to avoid multiplying booking totals.
    refund_totals = (
        db.query(
            Refund.booking_id.label("booking_id"),
            func.sum(Refund.amount).label("refund_amount"),
        )
        .group_by(Refund.booking_id)
        .subquery()
    )

    query = (
        db.query(
            Event.id.label("event_id"),
            Event.title.label("event_title"),
            Show.id.label("show_id"),
            Show.show_date.label("show_date"),
            func.coalesce(
                func.sum(
                    func.coalesce(
                        Booking.seat_count,
                        Booking.quantity,
                        0,
                    )
                ),
                0,
            ).label("tickets_sold"),
            func.coalesce(
                func.sum(Booking.grand_total),
                0,
            ).label("revenue"),
            func.coalesce(
                func.sum(refund_totals.c.refund_amount),
                0,
            ).label("refunds"),
        )
        .select_from(Booking)
        .outerjoin(Show, Booking.show_id == Show.id)
        .join(
            Event,
            func.coalesce(
                Booking.event_id,
                Show.event_id,
            ) == Event.id,
        )
        .outerjoin(
            refund_totals,
            refund_totals.c.booking_id == Booking.id,
        )
        .filter(func.lower(Booking.status) == "confirmed")
    )

    query = apply_event_access(query, current_user)

    if from_date:
        query = query.filter(Booking.created_at >= from_date)

    if to_date:
        query = query.filter(Booking.created_at <= to_date)

    rows = (
        query.group_by(
            Event.id,
            Event.title,
            Show.id,
            Show.show_date,
        )
        .order_by(Event.id, Show.show_date)
        .all()
    )

    results = [
        {
            "event_id": row.event_id,
            "event_title": row.event_title,
            "show_id": row.show_id,
            "show_date": row.show_date,
            "tickets_sold": int(row.tickets_sold or 0),
            "revenue": float(row.revenue or 0),
            "refunds": float(row.refunds or 0),
        }
        for row in rows
    ]

    return {
        "from_date": from_date,
        "to_date": to_date,
        "total_events": len(set(row.event_id for row in rows)),
        "items": results,
    }



@router.get("/occupancy")
def occupancy_report(
    show_id: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_report_access(current_user)

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date must be before or equal to to_date",
        )

    query = db.query(Show).join(
        Event, Show.event_id == Event.id
    )

    query = apply_event_access(query, current_user)

    if show_id is not None:
        query = query.filter(Show.id == show_id)

    if from_date:
        query = query.filter(Show.start_time >= from_date)

    if to_date:
        query = query.filter(Show.start_time <= to_date)

    shows = query.order_by(Show.start_time).all()

    results = []

    for show in shows:
        seats = db.query(Seat).filter(
            Seat.screen_id == show.screen_id,
            Seat.is_active == True,
        ).all()

        booked = (
            db.query(Seat.category, func.count(BookedSeat.id))
            .join(BookedSeat, BookedSeat.seat_id == Seat.id)
            .join(Booking, Booking.id == BookedSeat.booking_id)
            .filter(
                BookedSeat.show_id == show.id,
                func.lower(Booking.status) == "confirmed",
            )
            .group_by(Seat.category)
            .all()
        )

        booked_by_category = {
            category: count for category, count in booked
        }

        categories = {}

        for seat in seats:
            category = seat.category
            categories[category] = categories.get(category, 0) + 1

        total_seats = len(seats)
        total_booked = sum(booked_by_category.values())

        category_results = []

        for category, capacity in categories.items():
            sold = booked_by_category.get(category, 0)

            category_results.append({
                "category": category,
                "total_seats": capacity,
                "booked_seats": sold,
                "available_seats": max(capacity - sold, 0),
                "occupancy_percentage": round(
                    sold / capacity * 100, 2
                ) if capacity else 0,
            })

        results.append({
            "show_id": show.id,
            "event_id": show.event_id,
            "show_date": show.show_date,
            "total_seats": total_seats,
            "booked_seats": total_booked,
            "available_seats": max(total_seats - total_booked, 0),
            "occupancy_percentage": round(
                total_booked / total_seats * 100, 2
            ) if total_seats else 0,
            "categories": category_results,
        })

    return {
        "total_shows": len(results),
        "items": results,
    }



@router.get("/top-events")
def top_events_report(
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_admin(current_user)

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date must be before or equal to to_date",
        )

    query = (
        db.query(
            Event.id.label("event_id"),
            Event.title.label("event_title"),
            func.count(Ticket.id).label("tickets_sold"),
        )
        .outerjoin(Ticket, Ticket.event_id == Event.id)
    )

    if from_date:
        query = query.filter(
            (Ticket.id.is_(None)) |
            (Ticket.created_at >= from_date)
        )

    if to_date:
        query = query.filter(
            (Ticket.id.is_(None)) |
            (Ticket.created_at <= to_date)
        )

    rows = (
        query.group_by(Event.id, Event.title)
        .order_by(func.count(Ticket.id).desc())
        .limit(10)
        .all()
    )

    return {
        "from_date": from_date,
        "to_date": to_date,
        "items": [
            {
                "event_id": row.event_id,
                "event_title": row.event_title,
                "tickets_sold": row.tickets_sold,
            }
            for row in rows
        ],
    }



@router.get("/refunds")
def refunds_report(
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_admin(current_user)

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date must be before or equal to to_date",
        )

    query = db.query(
        Refund.reason,
        func.count(Refund.id).label("refund_count"),
        func.coalesce(func.sum(Refund.amount), 0).label("total_amount"),
    )

    if from_date:
        query = query.filter(Refund.created_at >= from_date)

    if to_date:
        query = query.filter(Refund.created_at <= to_date)

    rows = query.group_by(Refund.reason).all()

    return {
        "total_refunds": sum(row.refund_count for row in rows),
        "total_amount": sum(
            float(row.total_amount or 0) for row in rows
        ),
        "items": [
            {
                "reason": row.reason,
                "refund_count": row.refund_count,
                "total_amount": float(row.total_amount or 0),
            }
            for row in rows
        ],
    }
