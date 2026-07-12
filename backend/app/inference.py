"""Backend-neutral inference contracts and deterministic development adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol

from .contracts import Detection, DetectionMessage, NormalizedBox


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    capture_timestamp: datetime
    payload: bytes = b""


@dataclass(frozen=True)
class BackendHealth:
    backend_id: str
    model_id: str
    ready: bool
    device: str


class InferenceBackend(Protocol):
    async def load(self) -> None: ...
    async def detect(self, frame: Frame) -> list[Detection]: ...
    async def health(self) -> BackendHealth: ...
    async def close(self) -> None: ...


class FakeInferenceBackend:
    """Stable person result for CI and UI work without ML weights or hardware."""

    backend_id = "fake"

    def __init__(self, model_id: str = "fake-person-v1") -> None:
        self.model_id = model_id
        self._loaded = False

    async def load(self) -> None:
        self._loaded = True

    async def detect(self, frame: Frame) -> list[Detection]:
        if not self._loaded:
            raise RuntimeError("inference backend is not loaded")
        if frame.width < 2 or frame.height < 2:
            return []
        return [
            Detection(
                class_name="person",
                confidence=0.91,
                box=NormalizedBox(x=0.25, y=0.15, width=0.25, height=0.60),
            )
        ]

    async def health(self) -> BackendHealth:
        return BackendHealth(self.backend_id, self.model_id, self._loaded, "synthetic")

    async def close(self) -> None:
        self._loaded = False


class DetectionWorker:
    """Runs a backend and applies class/confidence filtering to a sampled frame."""

    def __init__(
        self,
        backend: InferenceBackend,
        allowed_classes: frozenset[str],
        confidence_threshold: float,
        publish: Callable[[DetectionMessage], Awaitable[None]],
    ) -> None:
        self.backend = backend
        self.allowed_classes = allowed_classes
        self.confidence_threshold = confidence_threshold
        self.publish = publish
        self.sequence = 0
        self.processed_frames = 0
        self.failed_frames = 0

    async def process(self, frame: Frame) -> DetectionMessage:
        started = perf_counter()
        try:
            detections = await self.backend.detect(frame)
            filtered = [
                item
                for item in detections
                if item.class_name in self.allowed_classes
                and item.confidence >= self.confidence_threshold
            ]
            health = await self.backend.health()
            message = DetectionMessage(
                sequence=self.sequence,
                capture_timestamp=frame.capture_timestamp,
                result_timestamp=datetime.now(UTC),
                source_width=frame.width,
                source_height=frame.height,
                backend_id=health.backend_id,
                model_id=health.model_id,
                inference_ms=(perf_counter() - started) * 1000,
                detections=filtered,
            )
            self.sequence += 1
            self.processed_frames += 1
            await self.publish(message)
            return message
        except Exception:
            self.failed_frames += 1
            raise
