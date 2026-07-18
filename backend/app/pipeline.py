"""Sampling orchestration with latest-frame-wins backpressure."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .inference import DetectionWorker, Frame
from .scheduling import FairFrameScheduler


@dataclass(frozen=True)
class SourceStatus:
    state: str
    reconnects: int
    last_error: str | None


class ReconnectingFrameSource:
    """Reopen a frame adapter with bounded exponential backoff after failures."""

    def __init__(
        self,
        source_factory: Callable[[], AsyncIterator[Frame]],
        *,
        on_state: Callable[[str], None] | None = None,
        initial_delay: float = 0.25,
        maximum_delay: float = 10,
        sleep: Callable[[float], Coroutine[Any, Any, None]] = asyncio.sleep,
    ) -> None:
        self.source_factory = source_factory
        self.on_state = on_state
        self.initial_delay = initial_delay
        self.maximum_delay = maximum_delay
        self.sleep = sleep
        self.state = "connecting"
        self.reconnects = 0
        self.last_error: str | None = None

    @property
    def status(self) -> SourceStatus:
        return SourceStatus(self.state, self.reconnects, self.last_error)

    def _transition(self, state: str) -> None:
        if self.state == state:
            return
        self.state = state
        if self.on_state:
            self.on_state(state)

    async def frames(self) -> AsyncIterator[Frame]:
        delay = self.initial_delay
        while True:
            try:
                async for frame in self.source_factory():
                    self.last_error = None
                    delay = self.initial_delay
                    self._transition("ready")
                    yield frame
                raise RuntimeError("frame source ended")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.last_error = type(error).__name__
                self.reconnects += 1
                self._transition("degraded")
                await self.sleep(delay)
                delay = min(delay * 2, self.maximum_delay)
                self._transition("connecting")


class SyntheticFrameSource:
    """Deterministic frame clock for local development and integration tests."""

    def __init__(
        self, fps: float, width: int = 1280, height: int = 720, decoded_image: bool = False
    ) -> None:
        self.interval = 1 / fps
        self.width = width
        self.height = height
        self.decoded_image = decoded_image

    async def frames(self) -> AsyncIterator[Frame]:
        image = None
        if self.decoded_image:
            try:
                import numpy as np
            except ImportError as error:
                raise RuntimeError(
                    "decoded synthetic frames require the Ultralytics runtime extra"
                ) from error
            image = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        while True:
            yield Frame(self.width, self.height, datetime.now(UTC), image)
            await asyncio.sleep(self.interval)


class OpenCvRestreamSource:
    """Decode only go2rtc's local restream, never the physical camera URL."""

    def __init__(
        self,
        restream_url: str,
        fps: float,
        capture_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.restream_url = restream_url
        self.interval = 1 / fps
        self.capture_factory = capture_factory
        self.clock = clock
        self.dropped_frames = 0

    async def frames(self) -> AsyncIterator[Frame]:
        capture_factory = self.capture_factory
        if capture_factory is None:
            try:
                import cv2
            except ImportError as error:
                raise RuntimeError(
                    "restream decoding requires the Ultralytics runtime extra"
                ) from error
            capture_factory = cv2.VideoCapture
        capture = await asyncio.to_thread(capture_factory, self.restream_url)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError("local video restream is unavailable")
        clock = self.clock or asyncio.get_running_loop().time
        next_sample_at = clock()
        try:
            while True:
                ok = await asyncio.to_thread(capture.grab)
                if not ok:
                    raise RuntimeError("local video restream ended")
                now = clock()
                if now < next_sample_at:
                    self.dropped_frames += 1
                    continue
                ok, image = await asyncio.to_thread(capture.retrieve)
                if not ok:
                    raise RuntimeError("local video restream ended")
                height, width = image.shape[:2]
                yield Frame(width, height, datetime.now(UTC), image)
                next_sample_at = now + self.interval
        finally:
            await asyncio.to_thread(capture.release)


class InferencePipeline:
    def __init__(
        self,
        worker: DetectionWorker,
        source_dropped_frames: Callable[[], int] | None = None,
        source_status: Callable[[], SourceStatus] | None = None,
        camera_id: str | None = None,
    ) -> None:
        self.worker = worker
        self.camera_id = camera_id or worker.default_camera_id
        self.scheduler = FairFrameScheduler()
        self.source_dropped_providers: dict[str, Callable[[], int]] = {
            self.camera_id: source_dropped_frames or (lambda: 0)
        }
        self.source_status_providers: dict[str, Callable[[], SourceStatus]] = {}
        if source_status:
            self.source_status_providers[self.camera_id] = source_status
        self._consumer: asyncio.Task[None] | None = None
        self._producer: asyncio.Task[None] | None = None
        self._producers: dict[str, asyncio.Task[None]] = {}
        self._source_errors: dict[str, str | None] = {}
        self.consumer_error: str | None = None
        self._accepting_frames = True

    @property
    def dropped_frames(self) -> int:
        return self.scheduler.dropped_total + sum(
            provider() for provider in self.source_dropped_providers.values()
        )

    @property
    def source_error(self) -> str | None:
        provider = self.source_status_providers.get(self.camera_id)
        if provider:
            return provider().last_error
        return self._source_errors.get(self.camera_id)

    @source_error.setter
    def source_error(self, value: str | None) -> None:
        self._source_errors[self.camera_id] = value

    @property
    def source_state(self) -> str:
        provider = self.source_status_providers.get(self.camera_id)
        if provider:
            return provider().state
        return "error" if self._source_errors.get(self.camera_id) else "ready"

    @property
    def source_reconnects(self) -> int:
        provider = self.source_status_providers.get(self.camera_id)
        return provider().reconnects if provider else 0

    @property
    def camera_metrics(self) -> dict[str, dict[str, object]]:
        camera_ids = set(self.source_dropped_providers) | set(self._producers)
        return {
            camera_id: {
                "dropped_frames": self.scheduler.dropped.get(camera_id, 0)
                + self.source_dropped_providers.get(camera_id, lambda: 0)(),
                "source_state": (
                    self.source_status_providers[camera_id]().state
                    if camera_id in self.source_status_providers
                    else "error"
                    if self._source_errors.get(camera_id)
                    else "ready"
                ),
                "source_reconnects": (
                    self.source_status_providers[camera_id]().reconnects
                    if camera_id in self.source_status_providers
                    else 0
                ),
            }
            for camera_id in sorted(camera_ids)
        }

    async def start(self, source: AsyncIterator[Frame], camera_id: str | None = None) -> None:
        if self._consumer is not None:
            raise RuntimeError("inference pipeline is already started")
        self._consumer = asyncio.create_task(self._consume())
        await self.add_source(camera_id or self.camera_id, source)

    async def add_source(
        self,
        camera_id: str,
        source: AsyncIterator[Frame],
        *,
        source_dropped_frames: Callable[[], int] | None = None,
        source_status: Callable[[], SourceStatus] | None = None,
    ) -> None:
        if not camera_id:
            raise ValueError("camera identifier is required")
        if camera_id in self._producers:
            raise ValueError("camera source is already registered")
        if source_dropped_frames:
            self.source_dropped_providers[camera_id] = source_dropped_frames
        else:
            self.source_dropped_providers.setdefault(camera_id, lambda: 0)
        if source_status:
            self.source_status_providers[camera_id] = source_status
        producer = asyncio.create_task(self._sample(camera_id, source))
        self._producers[camera_id] = producer
        if camera_id == self.camera_id:
            self._producer = producer

    async def _consume(self) -> None:
        while True:
            scheduled = await self.scheduler.next()
            try:
                await self.worker.process(scheduled.frame, scheduled.camera_id)
                self.consumer_error = None
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.consumer_error = type(error).__name__

    async def _sample(self, camera_id: str, source: AsyncIterator[Frame]) -> None:
        try:
            async for frame in source:
                if self._accepting_frames:
                    await self.scheduler.submit(camera_id, frame)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Deliberately report only adapter state, never its source URL.
            self._source_errors[camera_id] = type(error).__name__

    def pause(self) -> None:
        self._accepting_frames = False
        self.scheduler.reset()

    def resume(self) -> None:
        self._accepting_frames = True

    def reset(self) -> None:
        self.scheduler.reset()

    async def close(self) -> None:
        tasks = [*self._producers.values()]
        if self._consumer:
            tasks.append(self._consumer)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
