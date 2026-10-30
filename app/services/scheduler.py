
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.booking import Booking
from app.models.show import Show
from app.models.event import Event
from app.models.user import User
from app.services.notification_service import send_email_notification
from app.services.redis_client import redis_client
from app.services.seat_lock_service import lock_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


def expire_pending_bookings():
    """Expire unpaid bookings and release their Redis seat locks."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()

        expired = (
            db.query(Booking)
            .filter(
                Booking.status == "Pending Payment",
                Booking.expires_at.isnot(None),
                Booking.expires_at <= now,
            )
            .all()
        )

        for booking in expired:
            for booked_seat in booking.booked_seats:
                key = lock_key(booking.show_id, booked_seat.seat_id)
                owner = redis_client.get(key)

                if isinstance(owner, bytes):
                    owner = owner.decode("utf-8")

                if owner and booking.customer_id is not None:
                    if str(owner) == str(booking.customer_id):
                        redis_client.delete(key)

            booking.status = "Expired"

        if expired:
            db.commit()
            logger.info(
                "Expired %s bookings and released their seat locks",
                len(expired),
            )

    except Exception:
        db.rollback()
        logger.exception("Expired booking job failed")
    finally:
        db.close()


def send_upcoming_show_reminders():
    """Send reminders to confirmed customers once per booking."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        deadline = now + timedelta(hours=3)

        bookings = (
            db.query(Booking)
            .join(Show, Booking.show_id == Show.id)
            .filter(
                Booking.status == "Confirmed",
                Booking.reminder_sent_at.is_(None),
                Show.status == "Scheduled",
                Show.start_time > now,
                Show.start_time <= deadline,
            )
            .all()
        )

        for booking in bookings:
            customer = (
                db.query(User)
                .filter(User.id == booking.customer_id)
                .first()
            )
            show = (
                db.query(Show)
                .filter(Show.id == booking.show_id)
                .first()
            )

            if not customer or not getattr(customer, "email", None):
                logger.warning(
                    "No customer email for booking %s",
                    booking.id,
                )
                continue

            if not show:
                continue

            sent = send_email_notification(
                recipient=customer.email,
                subject="Upcoming Show Reminder",
                body=(
                    "Your show starts within the next 3 hours.\n\n"
                    "Booking: {}\n"
                    "Event ID: {}\n"
                    "Show ID: {}\n"
                    "Start time: {}\n"
                ).format(
                    booking.booking_number or booking.id,
                    show.event_id,
                    show.id,
                    show.start_time,
                ),
            )

            if sent:
                booking.reminder_sent_at = datetime.utcnow()
                db.commit()
            else:
                logger.warning(
                    "Reminder email failed for booking %s; it can be retried",
                    booking.id,
                )

    except Exception:
        db.rollback()
        logger.exception("Show reminder job failed")
    finally:
        db.close()


def complete_finished_shows():
    """Mark scheduled shows Completed after their end time."""
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()

        finished = (
            db.query(Show)
            .filter(
                Show.status == "Scheduled",
                Show.end_time <= now,
            )
            .all()
        )

        for show in finished:
            show.status = "Completed"

        if finished:
            db.commit()
            logger.info("Marked %s shows Completed", len(finished))

    except Exception:
        db.rollback()
        logger.exception("Show completion job failed")
    finally:
        db.close()


def complete_finished_events():
    """Complete published events when all their shows have completed."""
    db: Session = SessionLocal()
    try:
        events = (
            db.query(Event)
            .filter(
                Event.status.in_(["Published", "Scheduled", "Active"])
            )
            .all()
        )

        completed_count = 0

        for event in events:
            shows = (
                db.query(Show)
                .filter(Show.event_id == event.id)
                .all()
            )

            if shows and all(show.status == "Completed" for show in shows):
                event.status = "Completed"
                completed_count += 1

        if completed_count:
            db.commit()
            logger.info("Marked %s events Completed", completed_count)

    except Exception:
        db.rollback()
        logger.exception("Event completion job failed")
    finally:
        db.close()


def start_scheduler():
    """Register and start all scheduled jobs."""
    if scheduler.running:
        logger.info("Scheduler is already running")
        return

    scheduler.add_job(
        expire_pending_bookings,
        "interval",
        minutes=1,
        id="expire_pending_bookings",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        send_upcoming_show_reminders,
        "interval",
        minutes=30,
        id="show_reminders",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        complete_finished_shows,
        "interval",
        minutes=15,
        id="complete_finished_shows",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        complete_finished_events,
        "interval",
        hours=24,
        id="complete_finished_events",
        replace_existing=True,
        max_instances=1,
    )

    logger.info("Starting Level 11 scheduler...")
    scheduler.start()

    job_ids = [job.id for job in scheduler.get_jobs()]
    print("Registered scheduler jobs:", job_ids, flush=True)
    logger.info("Level 11 scheduler started")


def stop_scheduler():
    """Stop the scheduler during application shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Level 11 scheduler stopped")
