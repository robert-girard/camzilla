import asyncio
import importlib.util
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .alerts import AlertEngine, build_alert_engine
from .backup import build_backup, validate_backup
from .config import Settings, get_settings
from .contracts import (
    AlertPayload,
    AlertRule,
    AlertRuleUpdate,
    AlertRuntimeStatus,
    BackupDocument,
    BackupRestoreRequest,
    BackupValidationRequest,
    BackupValidationResponse,
    CameraCreate,
    EventPage,
    GlobalConfiguration,
    InferenceCapabilitiesResponse,
    InferenceSelectionRequest,
    PtzCapabilityResponse,
    PtzMoveRequest,
    PtzMoveResponse,
    RecordingResponse,
    StreamDescriptor,
)
from .inference import DetectionWorker, FakeInferenceBackend, InferenceBackend, UltralyticsBackend
from .media import ClipRecorder, MediaStorageError, MediaStore, StoredMedia
from .model_registry import ModelRegistry
from .persistence import ConfigurationConflictError, Database, Repository
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
    active_id = capability_id(
        backend_health.backend_id, backend_health.model_id, backend_health.target
    )
    database = Database(settings.database_url)
    await asyncio.to_thread(database.migrate)
    repository = Repository(database)
    await asyncio.to_thread(repository.seed, settings.camera_name, active_id)
    app.state.database = database
    app.state.repository = repository
    app.state.media_failures = 0
    media_store: MediaStore | None = None
    clip_recorder: ClipRecorder | None = None

    async def clip_complete(event_id: str, stored: StoredMedia) -> None:
        await asyncio.to_thread(repository.update_event_media, event_id, clip_path=stored.path)
        await asyncio.to_thread(repository.clear_media_paths, stored.removed_paths)

    async def clip_failed(_event_id: str) -> None:
        app.state.media_failures += 1

    if settings.media_enabled:
        media_store = MediaStore(Path(settings.media_root), settings.media_quota_bytes)
        clip_recorder = ClipRecorder(
            media_store,
            fps=settings.inference_fps,
            duration_seconds=settings.clip_duration_seconds,
            pre_roll_seconds=settings.clip_pre_roll_seconds,
            on_complete=clip_complete,
            on_failed=clip_failed,
        )
    app.state.media_store = media_store
    app.state.clip_recorder = clip_recorder

    async def persist_event(payload: AlertPayload) -> None:
        event_type = (
            "detection"
            if payload.event.rule_id != "stream-state"
            else next(iter(payload.event.matched_classes), "stream-state")
        )
        snapshot_path = None
        if media_store is not None and payload.attachments:
            try:
                stored = await asyncio.to_thread(
                    media_store.save_snapshot,
                    payload.event.camera_name,
                    str(payload.event.id),
                    payload.attachments[0].data,
                )
                snapshot_path = stored.path
                await asyncio.to_thread(repository.clear_media_paths, stored.removed_paths)
            except MediaStorageError:
                app.state.media_failures += 1
        await asyncio.to_thread(
            repository.record_event,
            event_id=str(payload.event.id),
            camera_id=payload.event.camera_name,
            rule_id=payload.event.rule_id if payload.event.rule_id != "stream-state" else None,
            event_type=event_type,
            triggered_at=payload.event.triggered_at,
            categories=sorted(payload.event.matched_classes),
            snapshot_path=snapshot_path,
        )
        if event_type == "detection" and clip_recorder is not None:
            clip_recorder.trigger(str(payload.event.id), payload.event.camera_name)

    hub = DetectionHub()
    app.state.hub = hub
    alert_engine = build_alert_engine(
        settings,
        event_sink=persist_event,
        frame_observer=clip_recorder.observe if clip_recorder else None,
    )
    persisted_configuration = await asyncio.to_thread(repository.configuration)
    persisted_rule = next(
        item for item in persisted_configuration.alert_rules if item.id == "person-detected"
    )
    alert_engine.rule = AlertRule(
        id=persisted_rule.id,
        camera_name=settings.camera_name,
        target_classes=frozenset(persisted_rule.target_categories),
        confidence_threshold=persisted_rule.confidence_threshold,
        debounce_seconds=persisted_rule.debounce_seconds,
        enabled=persisted_rule.enabled,
        schedule_start=persisted_rule.schedule_start,
        schedule_end=persisted_rule.schedule_end,
        zone=(
            [(point.x, point.y) for point in persisted_rule.zone.points]
            if persisted_rule.zone
            else None
        ),
    )
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
    if settings.inference_backend == "ultralytics":
        artifact = registry.artifact_status(settings.model_id, Path(settings.resolved_model_path))
        existing = specs[active_id]
        specs[active_id] = CapabilitySpec(
            existing.capability.model_copy(update={"available": True, "unavailable_reason": None}),
            str(artifact.path),
            existing.requested_device,
        )

    async def persist_selection(selected_id: str) -> None:
        await asyncio.to_thread(repository.set_active_capability, selected_id)

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
    persisted_id = await asyncio.to_thread(repository.active_capability_id)
    if persisted_id != active_id:
        persisted_spec = specs.get(persisted_id)
        if persisted_spec and persisted_spec.capability.available:
            await selection.select(persisted_id)
        else:
            selection.transition_state = "degraded"
            selection.transition_error = "persisted inference selection is unavailable"
    selection.selection_changed = persist_selection
    ptz_service = build_ptz_service(settings)
    app.state.ptz = ptz_service
    await asyncio.to_thread(
        repository.set_camera_capabilities,
        settings.camera_name,
        {
            "ptz": ptz_service.capability.model_dump(mode="json"),
            "runtime_state": "configured" if settings.camera_rtsp_url else "synthetic",
            "inference": [
                {
                    "id": spec.capability.id,
                    "target": spec.capability.target,
                    "available": spec.capability.available,
                    "unavailable_reason": spec.capability.unavailable_reason,
                }
                for spec in specs.values()
            ],
        },
    )
    heartbeat = asyncio.create_task(hub.heartbeat())
    try:
        yield
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await pipeline.close()
        await alert_engine.close()
        if clip_recorder:
            await clip_recorder.close()
        await app.state.worker.backend.close()
        database.close()


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
        "media": {
            "enabled": app.state.media_store is not None,
            "failures": app.state.media_failures,
            "recording_sessions": (
                len(app.state.clip_recorder.sessions) if app.state.clip_recorder else 0
            ),
        },
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


@app.get("/api/v1/config", response_model=GlobalConfiguration)
async def configuration() -> GlobalConfiguration:
    repository: Repository = app.state.repository
    return await asyncio.to_thread(repository.configuration)


@app.post("/api/v1/cameras", response_model=GlobalConfiguration, status_code=201)
async def add_camera(request: CameraCreate) -> GlobalConfiguration:
    repository: Repository = app.state.repository
    try:
        await asyncio.to_thread(
            repository.add_camera,
            expected_config_version=request.expected_config_version,
            camera_id=request.id,
            name=request.name,
            stream_secret_ref=request.stream_secret_ref,
        )
    except ConfigurationConflictError as error:
        raise HTTPException(status_code=409, detail="configuration version conflict") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail="camera already exists") from error
    return await asyncio.to_thread(repository.configuration)


@app.get("/api/v1/backup", response_model=BackupDocument)
async def export_backup() -> BackupDocument:
    repository: Repository = app.state.repository
    current = await asyncio.to_thread(repository.configuration)
    return build_backup(current)


@app.post("/api/v1/backup/validate", response_model=BackupValidationResponse)
async def validate_backup_document(request: BackupValidationRequest) -> BackupValidationResponse:
    return validate_backup(request.document)


@app.put("/api/v1/backup", response_model=GlobalConfiguration)
async def restore_backup(request: BackupRestoreRequest) -> GlobalConfiguration:
    selection: InferenceSelectionService = app.state.selection
    spec = selection.specs.get(request.document.active_capability_id)
    if spec is None or not spec.capability.available:
        raise HTTPException(status_code=422, detail="backup inference selection is unavailable")
    camera_categories = {
        camera.id: set(camera.allowed_categories) for camera in request.document.cameras
    }
    if any(
        not set(rule.target_categories) <= camera_categories[rule.camera_id]
        for rule in request.document.alert_rules
    ):
        raise HTTPException(status_code=422, detail="backup rule category is not enabled")
    repository: Repository = app.state.repository
    try:
        await asyncio.to_thread(
            repository.restore_backup,
            request.document,
            expected_config_version=request.expected_config_version,
        )
    except ConfigurationConflictError as error:
        raise HTTPException(status_code=409, detail="configuration version conflict") from error
    if selection.active_capability_id != request.document.active_capability_id:
        callback = selection.selection_changed
        selection.selection_changed = None
        try:
            await selection.select(request.document.active_capability_id)
        finally:
            selection.selection_changed = callback
    restored = await asyncio.to_thread(repository.configuration)
    restored_rule = next((item for item in restored.alert_rules if item.enabled), None)
    if restored_rule:
        alert_engine: AlertEngine = app.state.alert_engine
        camera = next(item for item in restored.cameras if item.id == restored_rule.camera_id)
        alert_engine.rule = AlertRule(
            id=restored_rule.id,
            camera_name=camera.name,
            target_classes=frozenset(restored_rule.target_categories),
            confidence_threshold=restored_rule.confidence_threshold,
            debounce_seconds=restored_rule.debounce_seconds,
            enabled=restored_rule.enabled,
            schedule_start=restored_rule.schedule_start,
            schedule_end=restored_rule.schedule_end,
            zone=(
                [(point.x, point.y) for point in restored_rule.zone.points]
                if restored_rule.zone
                else None
            ),
        )
    return restored


@app.put("/api/v1/alert-rules/{rule_id}", response_model=GlobalConfiguration)
async def update_alert_rule(rule_id: str, request: AlertRuleUpdate) -> GlobalConfiguration:
    repository: Repository = app.state.repository
    current = await asyncio.to_thread(repository.configuration)
    rule = next((item for item in current.alert_rules if item.id == rule_id), None)
    if rule is None:
        raise HTTPException(status_code=404, detail="alert rule not found")
    camera = next(item for item in current.cameras if item.id == rule.camera_id)
    if not set(request.target_categories) <= set(camera.allowed_categories):
        raise HTTPException(status_code=422, detail="rule category is not enabled for camera")
    zone = (
        [[point.x, point.y] for point in request.zone.points] if request.zone is not None else None
    )
    try:
        await asyncio.to_thread(
            repository.update_rule,
            rule_id,
            expected_config_version=request.expected_config_version,
            confidence_threshold=request.confidence_threshold,
            debounce_seconds=request.debounce_seconds,
            schedule_start=request.schedule_start,
            schedule_end=request.schedule_end,
            zone=zone,
            target_categories=request.target_categories,
        )
    except ConfigurationConflictError as error:
        raise HTTPException(status_code=409, detail="configuration version conflict") from error
    alert_engine: AlertEngine = app.state.alert_engine
    alert_engine.rule = AlertRule(
        id=rule_id,
        camera_name=camera.name,
        target_classes=frozenset(request.target_categories),
        confidence_threshold=request.confidence_threshold,
        debounce_seconds=request.debounce_seconds,
        enabled=rule.enabled,
        schedule_start=request.schedule_start,
        schedule_end=request.schedule_end,
        zone=([(point.x, point.y) for point in request.zone.points] if request.zone else None),
    )
    return await asyncio.to_thread(repository.configuration)


@app.get("/api/v1/events", response_model=EventPage)
async def event_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    camera_id: str | None = None,
    event_type: str | None = None,
    category: str | None = None,
    sort: Literal["asc", "desc"] = "desc",
) -> EventPage:
    repository: Repository = app.state.repository
    return await asyncio.to_thread(
        repository.list_events,
        page=page,
        page_size=page_size,
        camera_id=camera_id,
        event_type=event_type,
        category=category,
        descending=sort == "desc",
    )


@app.delete("/api/v1/events/{event_id}", status_code=204)
async def delete_event(event_id: UUID) -> Response:
    repository: Repository = app.state.repository
    removed = await asyncio.to_thread(repository.delete_event, str(event_id))
    if removed is None:
        raise HTTPException(status_code=404, detail="event not found")
    media_store: MediaStore | None = app.state.media_store
    if media_store:
        await asyncio.to_thread(media_store.delete, removed)
    return Response(status_code=204)


@app.get("/api/v1/events/{event_id}/{kind}")
async def event_media(event_id: UUID, kind: Literal["snapshot", "clip"]) -> FileResponse:
    repository: Repository = app.state.repository
    media_store: MediaStore | None = app.state.media_store
    if media_store is None:
        raise HTTPException(status_code=404, detail="media not found")
    try:
        relative = await asyncio.to_thread(repository.event_media_path, str(event_id), kind)
        if relative is None:
            raise FileNotFoundError
        path = await asyncio.to_thread(media_store.resolve, relative)
    except (KeyError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail="media not found") from error
    return FileResponse(
        path,
        media_type="image/jpeg" if kind == "snapshot" else "video/mp4",
        filename=path.name,
    )


@app.post(
    "/api/v1/cameras/{camera_name}/recordings",
    response_model=RecordingResponse,
    status_code=201,
)
async def start_manual_recording(camera_name: str) -> RecordingResponse:
    settings = get_settings()
    recorder: ClipRecorder | None = app.state.clip_recorder
    if camera_name != settings.camera_name:
        raise HTTPException(status_code=404, detail="camera not found")
    if recorder is None:
        raise HTTPException(status_code=409, detail="media recording is disabled")
    event_id = uuid4()
    try:
        recorder.start_manual(str(event_id), camera_name)
    except MediaStorageError as error:
        raise HTTPException(status_code=409, detail="manual recording is already active") from error
    repository: Repository = app.state.repository
    await asyncio.to_thread(
        repository.record_event,
        event_id=str(event_id),
        camera_id=camera_name,
        rule_id=None,
        event_type="manual-recording",
        triggered_at=datetime.now(UTC),
        categories=[],
    )
    return RecordingResponse(id=event_id, status="recording")


@app.delete(
    "/api/v1/recordings/{event_id}",
    response_model=RecordingResponse,
)
async def stop_manual_recording(event_id: UUID) -> RecordingResponse:
    recorder: ClipRecorder | None = app.state.clip_recorder
    if recorder is None or not recorder.stop_manual(str(event_id)):
        raise HTTPException(status_code=404, detail="recording not found")
    return RecordingResponse(id=event_id, status="processing")


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
