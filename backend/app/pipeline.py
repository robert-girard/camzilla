"""Sampling orchestration with latest-frame-wins backpressure."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime

from .inference import DetectionWorker, Frame
from .queueing import LatestItemQueue, consume_latest


class SyntheticFrameSource:
    """Deterministic frame clock for local development and integration tests."""

    def __init__(self, fps: float, width: int = 1280, height: int = 720) -> None:
        self.interval = 1 / fps
        self.width = width
        self.height = height

    async def frames(self) -> AsyncIterator[Frame]:
        while True:
            yield Frame(self.width, self.height, datetime.now(UTC))
            await asyncio.sleep(self.interval)


class OpenCvRestreamSource:
    """Decode only go2rtc's local restream, never the physical camera URL."""

    def __init__(self, restream_url: str, fps: float) -> None:
        self.restream_url = restream_url
        self.interval = 1 / fps

    async def frames(self) -> AsyncIterator[Frame]:
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError(
                "restream decoding requires the Ultralytics runtime extra"
            ) from error
        capture = await asyncio.to_thread(cv2.VideoCapture, self.restream_url)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError("local video restream is unavailable")
        try:
            while True:
                ok, image = await asyncio.to_thread(capture.read)
                if not ok:
                    raise RuntimeError("local video restream ended")
                height, width = image.shape[:2]
                yield Frame(width, height, datetime.now(UTC), image)
                await asyncio.sleep(self.interval)
        finally:
            await asyncio.to_thread(capture.release)


class InferencePipeline:
    def __init__(self, worker: DetectionWorker) -> None:
        self.worker = worker
        self.queue: LatestItemQueue[Frame] = LatestItemQueue()
        self._consumer: asyncio.Task[None] | None = None
        self._producer: asyncio.Task[None] | None = None
        self.source_error: str | None = None

    @property
    def dropped_frames(self) -> int:
        return self.queue.dropped

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
