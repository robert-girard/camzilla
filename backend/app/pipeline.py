"""Sampling orchestration with latest-frame-wins backpressure."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .inference import DetectionWorker, Frame
from .queueing import LatestItemQueue


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
    ) -> None:
        self.worker = worker
        self.queue: LatestItemQueue[Frame] = LatestItemQueue()
        self.source_dropped_frames = source_dropped_frames or (lambda: 0)
        self.source_status_provider = source_status
        self._consumer: asyncio.Task[None] | None = None
        self._producer: asyncio.Task[None] | None = None
        self._source_error: str | None = None
        self.consumer_error: str | None = None
        self._accepting_frames = True

    @property
    def dropped_frames(self) -> int:
        return self.source_dropped_frames() + self.queue.dropped

    @property
    def source_error(self) -> str | None:
        if self.source_status_provider:
            return self.source_status_provider().last_error
        return self._source_error

    @source_error.setter
    def source_error(self, value: str | None) -> None:
        self._source_error = value

    @property
    def source_state(self) -> str:
        if self.source_status_provider:
            return self.source_status_provider().state
        return "error" if self._source_error else "ready"

    @property
    def source_reconnects(self) -> int:
        return self.source_status_provider().reconnects if self.source_status_provider else 0

    async def start(self, source: AsyncIterator[Frame]) -> None:
        self._consumer = asyncio.create_task(self._consume())
        self._producer = asyncio.create_task(self._sample(source))

    async def _consume(self) -> None:
        while True:
            frame = await self.queue.get()
            try:
                await self.worker.process(frame)
                self.consumer_error = None
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.consumer_error = type(error).__name__
            finally:
                self.queue.done()

    async def _sample(self, source: AsyncIterator[Frame]) -> None:
        try:
            async for frame in source:
                if self._accepting_frames:
                    self.queue.put_latest(frame)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Deliberately report only adapter state, never its source URL.
            self._source_error = type(error).__name__

    def pause(self) -> None:
        self._accepting_frames = False
        self.queue.reset()

    def resume(self) -> None:
        self._accepting_frames = True

    def reset(self) -> None:
        self.queue.reset()

    async def close(self) -> None:
        for task in (self._producer, self._consumer):
            if task:
                task.cancel()
        for task in (self._producer, self._consumer):
            if task:
                with suppress(asyncio.CancelledError):
                    await task
