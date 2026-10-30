from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.router import get_current_user
from app.models.user import User
from app.models.booking import Booking
from app.models.ticket import Ticket
from app.models.show import Show
from app.models.event import Event
from app.models.venue import Venue, Screen
from app.services.ticket_service import (
    generate_ticket_pdf,
    verify_signed_qr,
)

router = APIRouter(tags=["Tickets & QR Entry"])


@router.get("/bookings/{booking_id}/ticket")
def download_booking_ticket(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if current_user.role != "Admin" and booking.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    pdf_data = generate_ticket_pdf(db, booking_id)

    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="{}.pdf"'.format(
                booking.booking_number
            )
        },
    )


@router.get("/shows/{show_id}/entries")
def get_show_entries(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("Admin", "Staff"):
        raise HTTPException(
            status_code=403,
            detail="Only Admin or Staff can view show entries",
        )

    show = db.query(Show).filter(Show.id == show_id).first()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    total_bookings = (
        db.query(Booking)
        .filter(
            Booking.show_id == show_id,
            Booking.status == "Confirmed",
        )
        .count()
    )

    entered_tickets = (
        db.query(Ticket)
        .join(Booking, Booking.id == Ticket.booking_id)
        .filter(
            Booking.show_id == show_id,
            Booking.status == "Confirmed",
            Ticket.status == "used",
        )
        .count()
    )

    return {
        "show_id": show_id,
        "total_confirmed_bookings": total_bookings,
        "entered_tickets": entered_tickets,
        "remaining_entries": max(total_bookings - entered_tickets, 0),
    }


@router.post("/tickets/scan")
def scan_ticket(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("Admin", "Staff"):
        raise HTTPException(
            status_code=403,
            detail="Only Staff can scan tickets",
        )

    qr_value = payload.get("qr_code")
    if not isinstance(qr_value, str) or not qr_value:
        raise HTTPException(status_code=422, detail="qr_code is required")

    booking_number = verify_signed_qr(qr_value)

    ticket = db.query(Ticket).filter(
        Ticket.qr_token == qr_value
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    booking = db.query(Booking).filter(
        Booking.id == ticket.booking_id
    ).first()

    if not booking or booking.booking_number != booking_number:
        raise HTTPException(status_code=400, detail="Invalid ticket")

    if booking.status != "Confirmed":
        raise HTTPException(
            status_code=400,
            detail="Ticket booking is not confirmed",
        )

    if ticket.status == "used":
        raise HTTPException(
            status_code=409,
            detail="Ticket already used at {}".format(ticket.scanned_at),
        )

    ticket.status = "used"
    ticket.scanned_at = __import__("datetime").datetime.utcnow()
    ticket.scanned_by = current_user.id
    db.commit()

    return {
        "message": "Ticket accepted",
        "booking_number": booking.booking_number,
        "customer_id": booking.customer_id,
        "seat_count": booking.seat_count,
        "seats": [item.seat_id for item in booking.booked_seats],
        "scanned_at": ticket.scanned_at,
    }