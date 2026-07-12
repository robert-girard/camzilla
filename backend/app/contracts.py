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
    inference_ms: float = Field(ge=0)
    detections: list[Detection]


class StreamDescriptor(BaseModel):
    camera_name: str
    webrtc_path: str
    diagnostic_fallback: Literal["hls", "mjpeg"] = "hls"
