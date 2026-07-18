from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import WebSocket

from app.inference import DetectionWorker, FakeInferenceBackend, Frame
from app.transport import DetectionHub


class RecordingWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_detection_hub_routes_only_the_subscribed_camera() -> None:
    hub = DetectionHub()
    front = RecordingWebSocket()
    side = RecordingWebSocket()
    await hub.connect(cast(WebSocket, front), "front-door")
    await hub.connect(cast(WebSocket, side), "side-door")
    backend = FakeInferenceBackend(model_id="fake-multi-v1")
    await backend.load()
    worker = DetectionWorker(
        backend,
        frozenset({"coco:person"}),
        0.5,
        hub.publish,
        camera_id="front-door",
    )
    worker.set_allowed_classes("side-door", frozenset({"coco:car"}))
    frame = Frame(640, 480, datetime.now(UTC))

    await worker.process(frame, "front-door")
    await worker.process(frame, "side-door")

    assert front.accepted and side.accepted
    assert [message["camera_id"] for message in front.messages] == ["front-door"]
    assert [message["camera_id"] for message in side.messages] == ["side-door"]
    assert front.messages[0]["detections"][0]["semantic_id"] == "coco:person"
    assert side.messages[0]["detections"][0]["semantic_id"] == "coco:car"
