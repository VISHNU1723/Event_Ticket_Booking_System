
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.auth.router import get_current_user
from app.models.show import Show
from app.models.venue import Seat
from app.services.redis_client import redis_client
from app.websockets.manager import seat_ws_manager

router = APIRouter(tags=["Live Seat Map"])


def get_token_user(token: str, db: Session):
    """Validate a JWT using the existing authentication function."""
    from fastapi.security import HTTPAuthorizationCredentials

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=token,
    )
    return get_current_user(credentials=credentials, db=db)


@router.websocket("/ws/shows/{show_id}/seats")
async def show_seat_updates(websocket: WebSocket, show_id: int):
    token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=1008, reason="Authentication token required")
        return

    db = SessionLocal()

    try:
        try:
            user = get_token_user(token, db)
        except Exception:
            await websocket.close(code=1008, reason="Invalid or expired token")
            return

        show = db.query(Show).filter(Show.id == show_id).first()
        if not show:
            await websocket.close(code=1008, reason="Show not found")
            return

        await seat_ws_manager.connect(show_id, websocket)

        seats = (
            db.query(Seat)
            .filter(Seat.screen_id == show.screen_id)
            .order_by(Seat.row_label, Seat.seat_number)
            .all()
        )

        seat_map = []

        for seat in seats:
            key = "lock:show:{}:seat:{}".format(show_id, seat.id)
            owner = redis_client.get(key)

            if not seat.is_active:
                seat_status = "Unavailable"
            elif owner is not None:
                seat_status = "Yours" if owner == str(user.id) else "Locked"
            else:
                seat_status = "Available"

            seat_map.append({
                "seat_id": seat.id,
                "row": seat.row_label,
                "seat_number": seat.seat_number,
                "category": seat.category,
                "status": seat_status,
            })

        await websocket.send_json({
            "event": "seat_map",
            "show_id": show_id,
            "seats": seat_map,
        })

        while True:
            # Keep the connection alive and detect client disconnects.
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    finally:
        seat_ws_manager.disconnect(show_id, websocket)
        db.close()
