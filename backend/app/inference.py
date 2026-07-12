"""Backend-neutral inference contracts and deterministic development adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol

from .contracts import Detection, DetectionMessage, NormalizedBox


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    capture_timestamp: datetime
    image: Any | None = None


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


class UltralyticsBackend:
    """YOLOv8 adapter loaded only in deployments that opt into Ultralytics."""

    backend_id = "ultralytics"

    def __init__(self, model_id: str, model_path: str, requested_device: str) -> None:
        self.model_id = model_id
        self.model_path = model_path
        self.requested_device = requested_device
        self.selected_device = "uninitialized"
        self.fallback_reason: str | None = None
        self._model: Any | None = None

    async def load(self) -> None:
        await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> None:
        try:
            import torch
            from ultralytics import YOLO
        except ImportError as error:
            raise RuntimeError(
                "Ultralytics backend requires `uv sync --extra ultralytics`"
            ) from error
        cuda_available = torch.cuda.is_available()
        if self.requested_device == "cuda" and not cuda_available:
            self.selected_device = "cpu"
            self.fallback_reason = "CUDA requested but unavailable; using CPU"
        elif self.requested_device == "auto":
            self.selected_device = "cuda" if cuda_available else "cpu"
            if not cuda_available:
                self.fallback_reason = "CUDA unavailable; using CPU"
        else:
            self.selected_device = self.requested_device
        self._model = YOLO(self.model_path)
        # Warm-up validates model/runtime initialization without retaining frames.
        import numpy as np

        self._model.predict(
            np.zeros((32, 32, 3), dtype=np.uint8), device=self.selected_device, verbose=False
        )

    async def detect(self, frame: Frame) -> list[Detection]:
        if self._model is None:
            raise RuntimeError("inference backend is not loaded")
        if frame.image is None:
            raise ValueError("Ultralytics backend requires a decoded frame image")
        return await asyncio.to_thread(self._detect_sync, frame)

    def _detect_sync(self, frame: Frame) -> list[Detection]:
        assert self._model is not None
        result = self._model.predict(frame.image, device=self.selected_device, verbose=False)[0]
        names = result.names
        detections: list[Detection] = []
        for box in result.boxes:
            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
            class_id = int(box.cls[0].item())
            detections.append(
                Detection(
                    class_name=str(names[class_id]),
                    confidence=float(box.conf[0].item()),
                    box=NormalizedBox(
                        x=max(0, x1) / frame.width,
                        y=max(0, y1) / frame.height,
                        width=min(frame.width, x2) / frame.width - max(0, x1) / frame.width,
                        height=min(frame.height, y2) / frame.height - max(0, y1) / frame.height,
                    ),
                )
            )
        return detections

    async def health(self) -> BackendHealth:
        return BackendHealth(
            self.backend_id,
            self.model_id,
            self._model is not None,
            self.selected_device,
        )

    async def close(self) -> None:
        self._model = None


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
