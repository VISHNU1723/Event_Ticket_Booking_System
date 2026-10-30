
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.auth.router import get_current_user, pwd_context

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "Admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.put("/organizers/{user_id}/approve")
def approve_organizer(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user or user.role != "Organizer":
        raise HTTPException(status_code=404, detail="Organizer not found")

    user.is_approved = True
    db.commit()
    db.refresh(user)

    return {
        "message": "Organizer approved successfully",
        "user_id": user.id,
        "is_approved": user.is_approved,
    }


class StaffCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    venue_id: int


@router.post("/staff", status_code=201)
def create_staff(
    data: StaffCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if db.query(User).filter(
        (User.username == data.username) | (User.email == str(data.email))
    ).first():
        raise HTTPException(status_code=409, detail="Username or email already exists")

    if len(data.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=400,
            detail="Password must not exceed 72 bytes",
        )

    staff = User(
        username=data.username,
        email=str(data.email),
        hashed_password=pwd_context.hash(data.password),
        role="Staff",
        is_active=True,
        is_approved=True,
    )

    # Venue assignment will be connected to the staff/venue model
    # in the venue-management module.
    db.add(staff)
    db.commit()
    db.refresh(staff)

    return {
        "id": staff.id,
        "username": staff.username,
        "email": staff.email,
        "role": staff.role,
        "venue_id": data.venue_id,
    }
