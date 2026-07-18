from datetime import datetime
from typing import Literal

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
