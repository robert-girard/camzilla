from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class NormalizedBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def remains_in_frame(self) -> "NormalizedBox":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("box must remain within normalized source frame")
        return self


class Detection(BaseModel):
    class_name: str
    confidence: float = Field(ge=0, le=1)
    box: NormalizedBox


class DetectionMessage(BaseModel):
    version: Literal["v1"] = "v1"
    sequence: int = Field(ge=0)
    capture_timestamp: datetime
    result_timestamp: datetime
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    backend_id: str
    model_id: str
    target: Literal["cpu", "gpu", "npu", "tpu"]
    device: str
    inference_ms: float = Field(ge=0)
    inference_fps: float = Field(ge=0)
    detections: list[Detection]


class StreamDescriptor(BaseModel):
    camera_name: str
    webrtc_path: str = "/api/v1/webrtc"
    diagnostic_fallback: Literal["hls", "mjpeg"] = "hls"


InferenceTarget = Literal["cpu", "gpu", "npu", "tpu"]
TransitionState = Literal["ready", "switching", "degraded"]


class InferenceCapability(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.:-]+$")
    backend_id: str
    model_id: str
    target: InferenceTarget
    device: str
    compatible: bool
    available: bool
    unavailable_reason: str | None = None
    active: bool = False

    @model_validator(mode="after")
    def availability_is_explained(self) -> "InferenceCapability":
        if self.available and (not self.compatible or self.unavailable_reason is not None):
            raise ValueError(
                "available capability must be compatible and have no unavailable reason"
            )
        if not self.available and not self.unavailable_reason:
            raise ValueError("unavailable capability must include a reason")
        return self


class InferenceSelection(BaseModel):
    capability_id: str
    backend_id: str
    model_id: str
    target: InferenceTarget
    device: str


class InferenceCapabilitiesResponse(BaseModel):
    active: InferenceSelection
    transition_state: TransitionState
    transition_error: str | None = None
    runtime_only: bool = True
    capabilities: list[InferenceCapability]


class InferenceSelectionRequest(BaseModel):
    capability_id: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9_.:-]+$")


PtzDirection = Literal["left", "right", "up", "down", "in", "out"]


class PtzCapabilityResponse(BaseModel):
    camera_name: str
    available: bool
    verified: bool
    unavailable_reason: str | None = None
    supports_continuous_move: bool
    supports_stop: bool = False
    max_speed: float = 0.3
    max_duration_seconds: float = 1.0


class PtzMoveRequest(BaseModel):
    direction: PtzDirection
    speed: float = Field(default=0.15, ge=0.05, le=0.3)
    duration_seconds: float = Field(default=1.0, ge=0.25, le=1.0)


class PtzMoveResponse(BaseModel):
    status: Literal["accepted"] = "accepted"
    direction: PtzDirection
    duration_seconds: float


class AlertRule(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]+$")
    camera_name: str
    target_classes: frozenset[str] = frozenset({"person"})
    confidence_threshold: float = Field(default=0.6, ge=0, le=1)
    debounce_seconds: float = Field(default=300, ge=1, le=86400)
    enabled: bool = True


class AlertEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    rule_id: str
    camera_name: str
    triggered_at: datetime
    detection_sequence: int = Field(ge=0)
    matched_classes: frozenset[str]


class AlertAttachment(BaseModel):
    filename: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    mime_type: str = Field(pattern=r"^[a-z0-9.+-]+/[a-z0-9.+-]+$")
    data: bytes = Field(max_length=8 * 1024 * 1024)


class AlertPayload(BaseModel):
    event: AlertEvent
    text: str = Field(min_length=1, max_length=2000)
    attachments: list[AlertAttachment] = Field(default_factory=list, max_length=10)


class AlertRuntimeStatus(BaseModel):
    rule: AlertRule
    requested_notifier: Literal["dry-run", "discord"]
    effective_notifier: Literal["dry-run", "discord"]
    external_delivery_configured: bool
    configuration_reason: str | None = None
    queued_events: int
    delivered_events: int
    dry_run_events: int
    failed_events: int
    dropped_events: int
    suppressed_events: int
    stream_state: Literal["connecting", "ready", "degraded"]
    stream_down_events: int
    stream_recovery_events: int
    last_event_at: datetime | None = None
    last_error: str | None = None
