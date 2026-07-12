import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from .config import Settings, get_settings
from .contracts import StreamDescriptor
from .inference import DetectionWorker, FakeInferenceBackend, InferenceBackend, UltralyticsBackend
from .pipeline import InferencePipeline, OpenCvRestreamSource, SyntheticFrameSource
from .transport import DetectionHub


def build_backend(settings: Settings) -> InferenceBackend:
    if settings.inference_backend == "ultralytics":
        return UltralyticsBackend(settings.model_id, settings.model_path, settings.inference_device)
    return FakeInferenceBackend(settings.model_id)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
    # The physical-camera URL is only supplied to go2rtc. Inference consumes its
    # local restream; no-camera development/CI remains deterministic.
    source = (
        OpenCvRestreamSource(settings.inference_restream_url, settings.inference_fps).frames()
        if settings.camera_rtsp_url
        else SyntheticFrameSource(settings.inference_fps).frames()
    )
    await pipeline.start(source)
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
        "bridge": {"state": "error" if pipeline.source_error else "ready"},
    }


@app.get("/api/v1/stream", response_model=StreamDescriptor)
async def stream_descriptor() -> StreamDescriptor:
    settings = get_settings()
    return StreamDescriptor(camera_name=settings.camera_name)


@app.post("/api/v1/webrtc")
async def webrtc_offer(request: Request) -> Response:
    """Proxy only WHEP signaling; the browser never learns a camera source URL."""
    offer = await request.body()
    if not offer:
        raise HTTPException(status_code=400, detail="missing WebRTC offer")
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            bridge_response = await client.post(
                f"http://go2rtc:1984/api/webrtc?src={settings.camera_name}",
                content=offer,
                headers={"content-type": "application/sdp"},
            )
        except httpx.RequestError as error:
            raise HTTPException(status_code=503, detail="video bridge unavailable") from error
    if bridge_response.status_code >= 400:
        raise HTTPException(status_code=503, detail="video bridge could not start stream")
    return Response(content=bridge_response.content, media_type="application/sdp")


@app.websocket("/api/v1/detections")
async def detections(websocket: WebSocket) -> None:
    hub: DetectionHub = websocket.app.state.hub
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
