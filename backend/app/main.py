import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .config import get_settings
from .contracts import StreamDescriptor
from .inference import DetectionWorker, FakeInferenceBackend, InferenceBackend, UltralyticsBackend
from .pipeline import InferencePipeline, SyntheticFrameSource
from .transport import DetectionHub


def build_backend(settings) -> InferenceBackend:
    if settings.inference_backend == "ultralytics":
        return UltralyticsBackend(settings.model_id, settings.model_path, settings.inference_device)
    return FakeInferenceBackend(settings.model_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    backend = build_backend(settings)
    await backend.load()
    hub = DetectionHub()
    app.state.backend = backend
    app.state.hub = hub
    app.state.worker = DetectionWorker(
        backend, settings.class_filter, settings.confidence_threshold, hub.publish
    )
    pipeline = InferencePipeline(app.state.worker)
    # Until the local restream is configured, fake mode uses no-camera synthetic
    # frames. It keeps development/CI deterministic and exercises transport.
    await pipeline.start(SyntheticFrameSource(settings.inference_fps).frames())
    app.state.pipeline = pipeline
    heartbeat = asyncio.create_task(hub.heartbeat())
    try:
        yield
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await pipeline.close()
        await backend.close()


app = FastAPI(title="Camzilla API", version="0.1.0", lifespan=lifespan)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> dict[str, object]:
    settings = get_settings()
    backend_health = await app.state.backend.health()
    worker: DetectionWorker = app.state.worker
    pipeline: InferencePipeline = app.state.pipeline
    return {
        "status": "ready",
        "camera_configured": settings.camera_rtsp_url is not None,
        "inference": {
            "backend": backend_health.backend_id,
            "model": backend_health.model_id,
            "ready": backend_health.ready,
            "device": backend_health.device,
        },
        "websocket_clients": app.state.hub.clients,
        "metrics": {
            "processed_frames": worker.processed_frames,
            "failed_frames": worker.failed_frames,
            "dropped_frames": pipeline.dropped_frames,
        },
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
