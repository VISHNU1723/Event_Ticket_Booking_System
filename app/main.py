
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth.router import router as auth_router
from app.auth.admin import router as admin_router
from app.routers.venue import router as venue_router
from app.routers.event import router as event_router
from app.routers.show import router as show_router
from app.websockets.seat_map import router as seat_map_router
from app.routers.booking import router as booking_router
from app.routers.payment import router as payment_router
from app.routers.ticket import router as ticket_router
from app.routers.waitlist import router as waitlist_router
from app.routers.reports import router as reports_router


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.scheduler import start_scheduler, stop_scheduler

    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(
    title="Event & Movie Ticket Booking System",
    description=(
        "Backend API for event discovery, ticket booking, payments, "
        "and QR ticket validation."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Register existing routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(venue_router)
app.include_router(event_router)
app.include_router(show_router)
app.include_router(seat_map_router)
app.include_router(booking_router)
app.include_router(payment_router)
app.include_router(ticket_router)
app.include_router(waitlist_router)
app.include_router(reports_router)


@app.get("/")
def home():
    return {
        "message": "Event & Movie Ticket Booking System API is running"
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/checkout", include_in_schema=False)
def checkout_page():
    return FileResponse(STATIC_DIR / "checkout.html")
