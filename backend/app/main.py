import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .config import get_settings
from .contracts import StreamDescriptor
from .inference import DetectionWorker, FakeInferenceBackend, Frame
from .transport import DetectionHub


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    backend = FakeInferenceBackend(settings.model_id)
    await backend.load()
    hub = DetectionHub()
    app.state.backend = backend
    app.state.hub = hub
    app.state.worker = DetectionWorker(
        backend, settings.class_filter, settings.confidence_threshold, hub.publish
    )
    heartbeat = asyncio.create_task(hub.heartbeat())
    try:
        yield
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await backend.close()


app = FastAPI(title="Camzilla API", version="0.1.0", lifespan=lifespan)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ready",
        "camera_configured": settings.camera_rtsp_url is not None,
        "inference": {"backend": settings.inference_backend, "model": settings.model_id},
        "websocket_clients": app.state.hub.clients,
    }


@app.get("/api/v1/stream", response_model=StreamDescriptor)
async def stream_descriptor() -> StreamDescriptor:
    settings = get_settings()
    return StreamDescriptor(camera_name=settings.camera_name, webrtc_path="/webrtc/front-door")


@app.websocket("/api/v1/detections")
async def detections(websocket: WebSocket) -> None:
    hub: DetectionHub = websocket.app.state.hub
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)


@app.post("/api/v1/demo/detection", include_in_schema=False)
async def demo_detection() -> dict[str, int]:
    """Deterministic local-only exercise endpoint; remove before authenticated phases."""
    worker: DetectionWorker = app.state.worker
    await worker.process(Frame(1280, 720, datetime.now(UTC)))
    return {"sequence": worker.sequence - 1}
