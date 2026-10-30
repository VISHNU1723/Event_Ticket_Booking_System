
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func

from app.models.booking import Booking, BookedSeat
from app.models.show import Show
from app.models.venue import Seat


OCCUPANCY_THRESHOLD = Decimal("80")
PRICE_INCREASE = Decimal("1.10")


def get_show_occupancy(db, show: Show) -> Decimal:
    """Calculate confirmed seat occupancy for a show."""

    total_seats = (
        db.query(func.count(Seat.id))
        .filter(
            Seat.screen_id == show.screen_id,
            Seat.is_active.is_(True),
        )
        .scalar()
    ) or 0

    if total_seats == 0:
        return Decimal("0")

    booked_seats = (
        db.query(func.count(func.distinct(BookedSeat.seat_id)))
        .join(Booking, Booking.id == BookedSeat.booking_id)
        .filter(
            BookedSeat.show_id == show.id,
            Booking.status == "Confirmed",
        )
        .scalar()
    ) or 0

    return (
        Decimal(str(booked_seats))
        / Decimal(str(total_seats))
        * Decimal("100")
    )


def get_dynamic_price(db, show: Show, original_price) -> int:
    """Increase the original price by 10% above 80% occupancy."""

    occupancy = get_show_occupancy(db, show)

    price = Decimal(str(original_price))

    if occupancy > OCCUPANCY_THRESHOLD:
        price *= PRICE_INCREASE

    return int(
        price.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
