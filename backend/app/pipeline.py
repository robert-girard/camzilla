"""Sampling orchestration with latest-frame-wins backpressure."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from .inference import DetectionWorker, Frame
from .queueing import LatestItemQueue, consume_latest


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
        self, worker: DetectionWorker, source_dropped_frames: Callable[[], int] | None = None
    ) -> None:
        self.worker = worker
        self.queue: LatestItemQueue[Frame] = LatestItemQueue()
        self.source_dropped_frames = source_dropped_frames or (lambda: 0)
        self._consumer: asyncio.Task[None] | None = None
        self._producer: asyncio.Task[None] | None = None
        self.source_error: str | None = None

    @property
    def dropped_frames(self) -> int:
        return self.source_dropped_frames() + self.queue.dropped

    async def start(self, source: AsyncIterator[Frame]) -> None:
        self._consumer = asyncio.create_task(consume_latest(self.queue, self.worker.process))
        self._producer = asyncio.create_task(self._sample(source))

    async def _sample(self, source: AsyncIterator[Frame]) -> None:
        try:
            async for frame in source:
                self.queue.put_latest(frame)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Deliberately report only adapter state, never its source URL.
            self.source_error = type(error).__name__

    async def close(self) -> None:
        for task in (self._producer, self._consumer):
            if task:
                task.cancel()
        for task in (self._producer, self._consumer):
            if task:
                with suppress(asyncio.CancelledError):
                    await task
