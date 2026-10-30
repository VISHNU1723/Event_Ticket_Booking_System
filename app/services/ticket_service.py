import os
import hmac
import hashlib
from io import BytesIO
from datetime import datetime
from decimal import Decimal

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from reportlab.lib.utils import ImageReader

from app.models.booking import Booking
from app.models.ticket import Ticket
from app.models.show import Show
from app.models.event import Event
from app.models.venue import Screen, Venue


QR_SECRET = os.getenv("SECRET_KEY")
if not QR_SECRET:
    raise RuntimeError("SECRET_KEY must be configured in .env")


def create_signed_qr(booking_number: str) -> str:
    """Create a booking number with an HMAC signature."""
    signature = hmac.new(
        QR_SECRET.encode("utf-8"),
        booking_number.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return "{}.{}".format(booking_number, signature)


def verify_signed_qr(qr_value: str) -> str:
    """Verify the QR signature and return the booking number."""
    try:
        booking_number, signature = qr_value.rsplit(".", 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid QR code")

    expected = hmac.new(
        QR_SECRET.encode("utf-8"),
        booking_number.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=400,
            detail="Invalid QR signature",
        )

    return booking_number


def generate_ticket_pdf(db: Session, booking_id: int) -> bytes:
    """Generate a PDF ticket for a confirmed booking."""
    booking = (
        db.query(Booking)
        .options(joinedload(Booking.booked_seats))
        .filter(Booking.id == booking_id)
        .first()
    )

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status != "Confirmed":
        raise HTTPException(
            status_code=400,
            detail="Tickets are available only for confirmed bookings",
        )

    show = db.query(Show).filter(Show.id == booking.show_id).first()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    event = db.query(Event).filter(Event.id == show.event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    screen = db.query(Screen).filter(Screen.id == show.screen_id).first()
    venue = (
        db.query(Venue).filter(Venue.id == screen.venue_id).first()
        if screen else None
    )

    ticket = (
        db.query(Ticket)
        .filter(Ticket.booking_id == booking.id)
        .first()
    )

    if not ticket:
        ticket = Ticket(
            booking_id=booking.id,
            event_id=event.id,
            ticket_code="TKT-{}".format(
               __import__("secrets").token_hex(5).upper()
            ),
            qr_token=create_signed_qr(booking.booking_number),
            status="valid",
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
    elif not ticket.qr_token:
        ticket.qr_token = create_signed_qr(booking.booking_number)
        db.commit()
        db.refresh(ticket)

    qr_value = ticket.qr_token
    qr_image = qrcode.make(qr_value)

    qr_buffer = BytesIO()
    qr_image.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    pdf_buffer = BytesIO()
    pdf = canvas.Canvas(pdf_buffer, pagesize=A4)
    width, height = A4

    pdf.setTitle("Ticket {}".format(booking.booking_number))
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(20 * mm, height - 25 * mm, "EVENT / MOVIE TICKET")

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(20 * mm, height - 40 * mm, str(event.title))

    pdf.setFont("Helvetica", 10)
    details = [
        ("Booking number", booking.booking_number),
        ("Show ID", str(show.id)),
        ("Show date and time", str(show.start_time)),
        ("Venue", venue.name if venue else "N/A"),
        ("Screen", screen.name if screen else "N/A"),
        (
            "Seats",
            ", ".join(str(item.seat_id) for item in booking.booked_seats),
        ),
        ("Seat count", str(booking.seat_count)),
        ("Amount paid", "INR {}".format(booking.grand_total)),
        ("Ticket code", ticket.ticket_code),
    ]

    y = height - 55 * mm
    for label, value in details:
        pdf.drawString(20 * mm, y, "{}: {}".format(label, value))
        y -= 9 * mm

    pdf.drawImage(
        ImageReader(qr_buffer),
        width - 65 * mm,
        height - 105 * mm,
        width=40 * mm,
        height=40 * mm,
    )

    pdf.setFont("Helvetica-Oblique", 9)
    pdf.drawString(
        20 * mm,
        20 * mm,
        "Present this ticket QR code at entry. Each ticket can be used once.",
    )

    pdf.save()
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()