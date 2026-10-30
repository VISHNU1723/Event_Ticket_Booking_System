import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.event import Event
from app.models.venue import Venue
from app.models.user import User
from app.auth.router import get_current_user
from app.services.redis_client import redis_client

router = APIRouter(prefix="/events", tags=["Events"])
logger = logging.getLogger(__name__)

CACHE_TTL = 300
EVENTS_CACHE_KEY = "events:published"
VALID_CATEGORIES = ["Movie", "Concert", "Comedy", "Sports", "Workshop"]
VALID_AGE_RATINGS = ["U", "UA", "A"]
VALID_EVENT_STATUSES = ["Draft", "Published", "Cancelled"]


def event_cache_key(event_id: int) -> str:
    return "events:{}".format(event_id)


def event_to_dict(event: Event) -> dict:
    result = {}
    for column in Event.__table__.columns:
        value = getattr(event, column.name)
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return result


def invalidate_event_cache(event_id: Optional[int] = None):
    try:
        keys = [EVENTS_CACHE_KEY]
        if event_id is not None:
            keys.append(event_cache_key(event_id))
        # Clear any paginated/filtered list caches if they exist.
        try:
            keys.extend(list(redis_client.scan_iter(match="events:list:*")))
        except Exception:
            pass
        redis_client.delete(*keys)
    except Exception:
        logger.exception("Could not invalidate event cache")


def get_cached_json(key: str):
    try:
        value = redis_client.get(key)
        if value:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return json.loads(value)
    except Exception:
        logger.exception("Redis cache read failed for key %s", key)
    return None


def set_cached_json(key: str, data):
    try:
        redis_client.set(key, json.dumps(data, default=str), ex=CACHE_TTL)
    except Exception:
        logger.exception("Redis cache write failed for key %s", key)


def ensure_future(value: datetime, field_name: str):
    now = datetime.now(value.tzinfo) if value.tzinfo is not None else datetime.now()
    if value <= now:
        raise HTTPException(status_code=400, detail="{} must be in the future".format(field_name))


class EventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    category: str = "Movie"
    language: str = "English"
    description: Optional[str] = None
    duration_minutes: int = Field(120, ge=30, le=300)
    age_rating: str = "U"
    status: str = "Draft"
    venue_id: int = Field(..., gt=0)
    event_date: datetime


class EventUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=150)
    category: Optional[str] = None
    language: Optional[str] = None
    description: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, ge=30, le=300)
    age_rating: Optional[str] = None
    status: Optional[str] = None
    venue_id: Optional[int] = Field(None, gt=0)
    event_date: Optional[datetime] = None


def require_organizer(user: User):
    if user.role != "Organizer" or not user.is_approved or not user.is_active:
        raise HTTPException(status_code=403, detail="Only approved, active organizers can manage events")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    require_organizer(current_user)
    ensure_future(payload.event_date, "Event date")
    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid event category")
    if payload.age_rating not in VALID_AGE_RATINGS:
        raise HTTPException(status_code=400, detail="Invalid age rating")
    if payload.status not in VALID_EVENT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid event status")

    event = Event(
        organizer_id=current_user.id, title=payload.title.strip(),
        category=payload.category, language=payload.language,
        description=payload.description, duration_minutes=payload.duration_minutes,
        age_rating=payload.age_rating, status=payload.status,
        venue_id=payload.venue_id, event_date=payload.event_date,
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
    except Exception:
        db.rollback()
        logger.exception("Failed to create event")
        raise HTTPException(status_code=409, detail="Could not create event; check unique fields and related records")
    invalidate_event_cache(event.id)
    return event


@router.get("")
def list_events(
    title: Optional[str] = Query(None, description="Partial title match"),
    city: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    sort_by: str = Query("event_date", pattern="^(event_date|price|title)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=400, detail="min_price must be less than or equal to max_price")

    query = db.query(Event).filter(Event.status == "Published")
    if city:
        query = query.join(Venue, Event.venue_id == Venue.id).filter(Venue.city.ilike("%{}%".format(city.strip())))
    if title:
        query = query.filter(Event.title.ilike("%{}%".format(title.strip())))
    if category:
        query = query.filter(Event.category.ilike(category.strip()))
    if language:
        query = query.filter(Event.language.ilike(language.strip()))
    if from_date:
        query = query.filter(Event.event_date >= from_date)
    if to_date:
        query = query.filter(Event.event_date <= to_date)

    price_column = getattr(Event, "ticket_price", None)
    if price_column is not None:
        if min_price is not None:
            query = query.filter(price_column >= min_price)
        if max_price is not None:
            query = query.filter(price_column <= max_price)
    elif min_price is not None or max_price is not None:
        raise HTTPException(status_code=400, detail="Price filtering is unavailable because Event has no ticket_price field")

    if sort_by == "title":
        sort_column = Event.title
    elif sort_by == "price":
        if price_column is None:
            raise HTTPException(status_code=400, detail="Price sorting is unavailable because Event has no ticket_price field")
        sort_column = price_column
    else:
        sort_column = Event.event_date
    query = query.order_by(sort_column.desc() if order == "desc" else sort_column.asc())

    # Cache only the unfiltered first page.
    use_cache = (
        not any([
            title,
            city,
            category,
            language,
            from_date,
            to_date,
            min_price is not None,
            max_price is not None,
        ])
        and sort_by == "event_date"
        and order == "asc"
        and skip == 0
        and limit == 10
    )

    cache_key = EVENTS_CACHE_KEY if use_cache else None

    if cache_key:
        cached = get_cached_json(cache_key)
        if cached is not None:
            return cached

    total = query.count()
    events = query.offset(skip).limit(limit).all()

    result = {
        "items": [event_to_dict(event) for event in events],
        "total": total,
        "skip": skip,
        "limit": limit,
    }

    if cache_key:
        set_cached_json(cache_key, result)

    return result


@router.get("/{event_id}")
def get_event(event_id: int, db: Session = Depends(get_db)):
    key = event_cache_key(event_id)
    cached = get_cached_json(key)
    if cached is not None:
        if cached.get("status") != "Published":
            raise HTTPException(status_code=404, detail="Published event not found")
        return cached
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event or event.status != "Published":
        raise HTTPException(status_code=404, detail="Published event not found")
    result = event_to_dict(event)
    set_cached_json(key, result)
    return result


@router.put("/{event_id}")
def update_event(event_id: int, payload: EventUpdate, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    require_organizer(current_user)
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.organizer_id != current_user.id and current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="You cannot manage this event")

    changes = payload.dict(exclude_unset=True)
    if "event_date" in changes and changes["event_date"] is not None:
        ensure_future(changes["event_date"], "Event date")
    if "category" in changes and changes["category"] not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid event category")
    if "age_rating" in changes and changes["age_rating"] not in VALID_AGE_RATINGS:
        raise HTTPException(status_code=400, detail="Invalid age rating")
    if "status" in changes and changes["status"] not in VALID_EVENT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid event status")
    for key, value in changes.items():
        setattr(event, key, value.strip() if key == "title" and isinstance(value, str) else value)
    try:
        db.commit()
        db.refresh(event)
    except Exception:
        db.rollback()
        logger.exception("Failed to update event %s", event_id)
        raise HTTPException(status_code=409, detail="Could not update event; check unique fields and related records")
    invalidate_event_cache(event.id)
    return event
