"""Bounded round-robin scheduling groundwork for shared multi-camera inference."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass

from .inference import Frame


@dataclass(frozen=True)
class ScheduledFrame:
    camera_id: str
    frame: Frame


class FairFrameScheduler:
    """Keep only each camera's newest frame and select ready cameras round-robin."""

    def __init__(self) -> None:
        self._latest: dict[str, Frame] = {}
        self._ready: deque[str] = deque()
        self._ready_set: set[str] = set()
        self._condition = asyncio.Condition()
        self.dropped: dict[str, int] = {}

    async def submit(self, camera_id: str, frame: Frame) -> None:
        if not camera_id:
            raise ValueError("camera identifier is required")
        async with self._condition:
            if camera_id in self._latest:
                self.dropped[camera_id] = self.dropped.get(camera_id, 0) + 1
            self._latest[camera_id] = frame
            if camera_id not in self._ready_set:
                self._ready.append(camera_id)
                self._ready_set.add(camera_id)
            self._condition.notify()

    async def next(self) -> ScheduledFrame:
        async with self._condition:
            while not self._ready:
                await self._condition.wait()
            camera_id = self._ready.popleft()
            self._ready_set.remove(camera_id)
            frame = self._latest.pop(camera_id)
            return ScheduledFrame(camera_id, frame)

    @property
    def pending_cameras(self) -> int:
        return len(self._latest)
