import asyncio
import importlib.util
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from .alerts import AlertEngine, build_alert_engine
from .config import Settings, get_settings
from .contracts import (
    AlertRuntimeStatus,
    InferenceCapabilitiesResponse,
    InferenceSelectionRequest,
    PtzCapabilityResponse,
    PtzMoveRequest,
    PtzMoveResponse,
    StreamDescriptor,
)
from .inference import DetectionWorker, FakeInferenceBackend, InferenceBackend, UltralyticsBackend
from .model_registry import ModelRegistry
from .pipeline import (
    InferencePipeline,
    OpenCvRestreamSource,
    ReconnectingFrameSource,
    SyntheticFrameSource,
)
from .ptz import PtzBusyError, PtzService, PtzUnavailableError, build_ptz_service
from .selection import (
    CapabilitySpec,
    InferenceSelectionService,
    SelectionError,
    build_capability_specs,
    capability_id,
)
from .transport import DetectionHub


def build_backend(settings: Settings) -> InferenceBackend:
    if settings.inference_backend == "ultralytics":
        return UltralyticsBackend(
            settings.model_id, settings.resolved_model_path, settings.inference_device
        )
    return FakeInferenceBackend()


def cuda_is_available() -> bool:
    if importlib.util.find_spec("torch") is None:
        return False
    import torch

    return bool(torch.cuda.is_available())


def backend_for_capability(spec: CapabilitySpec) -> InferenceBackend:
    if spec.capability.backend_id == "fake":
        return FakeInferenceBackend(
            spec.capability.model_id, spec.capability.device, spec.capability.target
        )
    if spec.capability.backend_id == "ultralytics" and spec.model_path:
        return UltralyticsBackend(spec.capability.model_id, spec.model_path, spec.requested_device)
    raise RuntimeError("unsupported inference capability")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    registry = ModelRegistry(
        settings.resolved_model_manifest_path, settings.resolved_model_directory
    )
    if settings.inference_backend == "ultralytics":
        configured_artifact = registry.artifact_status(
            settings.model_id, Path(settings.resolved_model_path)
        )
        if not configured_artifact.verified:
            raise RuntimeError("configured model artifact is not checksum verified")
    backend = build_backend(settings)
    await backend.load()
    backend_health = await backend.health()
    hub = DetectionHub()
    app.state.hub = hub
    alert_engine = build_alert_engine(settings)
    await alert_engine.start()
    app.state.alert_engine = alert_engine
    app.state.worker = DetectionWorker(
        backend,
        settings.class_filter,
        settings.confidence_threshold,
        hub.publish,
        alert_engine.observe,
    )
    # The physical-camera URL is only supplied to go2rtc. Inference consumes its
    # local restream; no-camera development/CI remains deterministic.
    if settings.camera_rtsp_url:
        restream_source = OpenCvRestreamSource(
            settings.inference_restream_url, settings.inference_fps
        )
        reconnecting_source = ReconnectingFrameSource(
            restream_source.frames, on_state=alert_engine.observe_stream_state
        )
        source = reconnecting_source.frames()
        pipeline = InferencePipeline(
            app.state.worker,
            source_dropped_frames=lambda: restream_source.dropped_frames,
            source_status=lambda: reconnecting_source.status,
        )
    else:
        alert_engine.observe_stream_state("ready")
        source = SyntheticFrameSource(
            settings.inference_fps, decoded_image=settings.inference_backend == "ultralytics"
        ).frames()
        pipeline = InferencePipeline(app.state.worker)
    await pipeline.start(source)
    app.state.pipeline = pipeline
    specs = build_capability_specs(
        registry,
        runtime_available=importlib.util.find_spec("ultralytics") is not None,
        cuda_available=cuda_is_available(),
        include_fake=settings.inference_backend == "fake",
    )
    active_id = capability_id(
        backend_health.backend_id, backend_health.model_id, backend_health.target
    )
    if settings.inference_backend == "ultralytics":
        artifact = registry.artifact_status(settings.model_id, Path(settings.resolved_model_path))
        existing = specs[active_id]
        specs[active_id] = CapabilitySpec(
            existing.capability.model_copy(update={"available": True, "unavailable_reason": None}),
            str(artifact.path),
            existing.requested_device,
        )
    selection = InferenceSelectionService(
        specs,
        active_id,
        backend_health,
        app.state.worker,
        pipeline,
        hub,
        backend_for_capability,
    )
    app.state.selection = selection
    app.state.ptz = build_ptz_service(settings)
    heartbeat = asyncio.create_task(hub.heartbeat())
    try:
        yield
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await pipeline.close()
        await alert_engine.close()
        await app.state.worker.backend.close()


app = FastAPI(title="Camzilla API", version="0.1.0", lifespan=lifespan)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> dict[str, object]:
    settings = get_settings()
    selection: InferenceSelectionService = app.state.selection
    backend_health = await selection.worker.backend.health()
    worker: DetectionWorker = app.state.worker
    pipeline: InferencePipeline = app.state.pipeline
    alert_engine: AlertEngine = app.state.alert_engine
    alert_status = alert_engine.status()
    camera_configured = settings.camera_rtsp_url is not None
    source_state = (
        pipeline.source_state if camera_configured or pipeline.source_error else "synthetic"
    )
    return {
        "status": (
            "ready"
            if backend_health.ready
            and source_state in {"ready", "synthetic"}
            and pipeline.consumer_error is None
            and selection.transition_state == "ready"
            and alert_status.last_error is None
            else "degraded"
        ),
        "camera": {
            "configured": camera_configured,
            "state": "not_configured" if not camera_configured else source_state,
        },
        "inference": {
            "backend": backend_health.backend_id,
            "model": backend_health.model_id,
            "ready": backend_health.ready,
            "device": backend_health.device,
            "target": backend_health.target,
            "fallback_reason": backend_health.fallback_reason,
            "transition_state": selection.transition_state,
            "transition_error": selection.transition_error,
            "state": "degraded" if pipeline.consumer_error else "ready",
            "last_error": pipeline.consumer_error,
        },
        "websocket_clients": app.state.hub.clients,
        "alerts": alert_status.model_dump(mode="json"),
        "metrics": {
            "processed_frames": worker.processed_frames,
            "failed_frames": worker.failed_frames,
            "observer_failures": worker.observer_failures,
            "dropped_frames": pipeline.dropped_frames,
            "source_reconnects": pipeline.source_reconnects,
            "inference_fps": worker.inference_fps,
            "last_inference_ms": worker.last_inference_ms,
        },
        "bridge": {"state": source_state},
    }


@app.get("/api/v1/alerts/status", response_model=AlertRuntimeStatus)
async def alert_status() -> AlertRuntimeStatus:
    alert_engine: AlertEngine = app.state.alert_engine
    return alert_engine.status()


@app.get("/api/v1/inference", response_model=InferenceCapabilitiesResponse)
async def inference_capabilities() -> InferenceCapabilitiesResponse:
    selection: InferenceSelectionService = app.state.selection
    return selection.response()


@app.put("/api/v1/inference/selection", response_model=InferenceCapabilitiesResponse)
async def select_inference(
    request: InferenceSelectionRequest,
) -> InferenceCapabilitiesResponse:
    selection: InferenceSelectionService = app.state.selection
    try:
        return await selection.select(request.capability_id)
    except SelectionError as error:
        status_code = (
            404 if error.kind == "not_found" else 409 if error.kind == "unavailable" else 503
        )
        raise HTTPException(status_code=status_code, detail=error.public_message) from error


@app.get(
    "/api/v1/cameras/{camera_name}/capabilities/ptz",
    response_model=PtzCapabilityResponse,
)
async def ptz_capability(camera_name: str) -> PtzCapabilityResponse:
    settings = get_settings()
    if camera_name != settings.camera_name:
        raise HTTPException(status_code=404, detail="camera not found")
    ptz: PtzService = app.state.ptz
    return ptz.capability


@app.post("/api/v1/cameras/{camera_name}/ptz", response_model=PtzMoveResponse)
async def move_ptz(camera_name: str, request: PtzMoveRequest) -> PtzMoveResponse:
    settings = get_settings()
    if camera_name != settings.camera_name:
        raise HTTPException(status_code=404, detail="camera not found")
    try:
        await app.state.ptz.move(request)
    except PtzUnavailableError as error:
        raise HTTPException(status_code=409, detail="PTZ is unavailable") from error
    except PtzBusyError as error:
        raise HTTPException(status_code=429, detail="PTZ command is throttled") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="PTZ command failed") from error
    return PtzMoveResponse(direction=request.direction, duration_seconds=request.duration_seconds)


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


@app.get("/api/v1/diagnostics/hls/{asset:path}", include_in_schema=False)
async def hls_diagnostic(asset: str, request: Request) -> Response:
    """Proxy diagnostic HLS without exposing the go2rtc administrative API."""
    allowed_assets = {"stream.m3u8", "playlist.m3u8", "segment.ts", "segment.m4s", "init.mp4"}
    if asset not in allowed_assets:
        raise HTTPException(status_code=404, detail="diagnostic asset unavailable")
    settings = get_settings()
    if asset == "stream.m3u8":
        bridge_path = f"api/stream.m3u8?src={settings.camera_name}"
    else:
        query = request.url.query
        bridge_path = f"api/hls/{asset}" + (f"?{query}" if query else "")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            bridge_response = await client.get(f"http://go2rtc:1984/{bridge_path}")
        except httpx.RequestError as error:
            raise HTTPException(status_code=503, detail="video bridge unavailable") from error
    if bridge_response.status_code >= 400:
        raise HTTPException(status_code=503, detail="diagnostic stream unavailable")
    content = bridge_response.content
    content_type = bridge_response.headers.get("content-type", "application/octet-stream")
    if asset == "stream.m3u8":
        content = content.replace(b"hls/", b"/api/v1/diagnostics/hls/")
    return Response(content=content, media_type=content_type)


@app.websocket("/api/v1/detections")
async def detections(websocket: WebSocket) -> None:
    hub: DetectionHub = websocket.app.state.hub
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
