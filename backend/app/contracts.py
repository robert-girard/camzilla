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
    schedule_start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    schedule_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    zone: list[tuple[float, float]] | None = None

    @model_validator(mode="after")
    def valid_schedule_and_zone(self) -> "AlertRule":
        if (self.schedule_start is None) != (self.schedule_end is None):
            raise ValueError("schedule start and end must be provided together")
        if self.zone is not None:
            if not 3 <= len(self.zone) <= 16:
                raise ValueError("zone must contain between 3 and 16 points")
            if any(not 0 <= coordinate <= 1 for point in self.zone for coordinate in point):
                raise ValueError("zone coordinates must be normalized")
        return self


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
    persistence_failures: int
    dropped_events: int
    suppressed_events: int
    stream_state: Literal["connecting", "ready", "degraded"]
    stream_down_events: int
    stream_recovery_events: int
    last_event_at: datetime | None = None
    last_error: str | None = None


class NormalizedPoint(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class PolygonZone(BaseModel):
    points: list[NormalizedPoint] = Field(min_length=3, max_length=16)

    @model_validator(mode="after")
    def has_area(self) -> "PolygonZone":
        area = sum(
            point.x * self.points[(index + 1) % len(self.points)].y
            - self.points[(index + 1) % len(self.points)].x * point.y
            for index, point in enumerate(self.points)
        )
        if abs(area) < 1e-6:
            raise ValueError("zone polygon must have non-zero area")
        return self


class CameraConfiguration(BaseModel):
    id: str
    name: str
    enabled: bool
    capabilities: dict[str, object]
    allowed_categories: list[str]
    catalog_revision: str
    version: int


class AlertRuleConfiguration(BaseModel):
    id: str
    camera_id: str
    enabled: bool
    target_categories: list[str]
    confidence_threshold: float
    debounce_seconds: float
    schedule_start: str | None = None
    schedule_end: str | None = None
    zone: PolygonZone | None = None
    version: int


class GlobalConfiguration(BaseModel):
    version: int
    active_capability_id: str
    cameras: list[CameraConfiguration]
    alert_rules: list[AlertRuleConfiguration]


class AlertRuleUpdate(BaseModel):
    expected_config_version: int = Field(ge=1)
    confidence_threshold: float = Field(ge=0, le=1)
    debounce_seconds: float = Field(ge=1, le=86400)
    schedule_start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    schedule_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    zone: PolygonZone | None = None
    target_categories: list[str] = Field(default_factory=lambda: ["person"], min_length=1)

    @model_validator(mode="after")
    def schedule_is_complete(self) -> "AlertRuleUpdate":
        if (self.schedule_start is None) != (self.schedule_end is None):
            raise ValueError("schedule start and end must be provided together")
        if len(self.target_categories) != len(set(self.target_categories)):
            raise ValueError("target categories must be unique")
        return self


class EventSummary(BaseModel):
    id: UUID
    camera_id: str
    rule_id: str | None
    event_type: str
    triggered_at: datetime
    categories: list[str]
    has_snapshot: bool
    has_clip: bool


class EventPage(BaseModel):
    items: list[EventSummary]
    page: int
    page_size: int
    total: int
    pages: int
