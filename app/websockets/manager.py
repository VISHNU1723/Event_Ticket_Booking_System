
from typing import Dict, Set

from fastapi import WebSocket


class SeatWebSocketManager:
    def __init__(self):
        self.connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, show_id: int, websocket: WebSocket):
        await websocket.accept()
        self.connections.setdefault(show_id, set()).add(websocket)

    def disconnect(self, show_id: int, websocket: WebSocket):
        if show_id in self.connections:
            self.connections[show_id].discard(websocket)

            if not self.connections[show_id]:
                del self.connections[show_id]

    async def broadcast(self, show_id: int, message: dict):
        clients = list(self.connections.get(show_id, set()))

        for websocket in clients:
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect(show_id, websocket)


seat_ws_manager = SeatWebSocketManager()
