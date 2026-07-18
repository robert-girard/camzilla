import asyncio

from fastapi import WebSocket

from .contracts import DetectionMessage


class DetectionHub:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, str | None] = {}
        self.last_message: DetectionMessage | None = None
        self.last_messages: dict[str, DetectionMessage] = {}

    @property
    def clients(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket, camera_id: str | None = None) -> None:
        await websocket.accept()
        self._clients[websocket] = camera_id
        latest = self.last_messages.get(camera_id) if camera_id else self.last_message
        if latest:
            await websocket.send_json(latest.model_dump(mode="json"))

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.pop(websocket, None)

    async def publish(self, message: DetectionMessage) -> None:
        self.last_message = message
        self.last_messages[message.camera_id] = message
        stale: list[WebSocket] = []
        for client, camera_id in self._clients.items():
            if camera_id is not None and camera_id != message.camera_id:
                continue
            try:
                await client.send_json(message.model_dump(mode="json"))
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(client)

    async def reset(self) -> None:
        self.last_message = None
        self.last_messages.clear()
        stale: list[WebSocket] = []
        for client in self._clients:
            try:
                await client.send_json({"type": "reset"})
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(client)

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(15)
            for client in tuple(self._clients):
                try:
                    await client.send_json({"type": "heartbeat"})
                except Exception:
                    self.disconnect(client)
