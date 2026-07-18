import asyncio

from fastapi import WebSocket

from .contracts import DetectionMessage


class DetectionHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self.last_message: DetectionMessage | None = None

    @property
    def clients(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        if self.last_message:
            await websocket.send_json(self.last_message.model_dump(mode="json"))

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def publish(self, message: DetectionMessage) -> None:
        self.last_message = message
        stale: list[WebSocket] = []
        for client in self._clients:
            try:
                await client.send_json(message.model_dump(mode="json"))
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(client)

    async def reset(self) -> None:
        self.last_message = None
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
