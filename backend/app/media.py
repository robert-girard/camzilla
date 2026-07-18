"""Filesystem media storage, bounded pre-roll clips, and quota retention."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .inference import Frame


class MediaStorageError(Exception):
    pass


@dataclass(frozen=True)
class StoredMedia:
    path: str
    removed_paths: tuple[str, ...]


class MediaStore:
    def __init__(self, root: Path, quota_bytes: int) -> None:
        self.root = root
        self.quota_bytes = quota_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _target(self, camera_id: str, event_id: str, suffix: str) -> Path:
        if not camera_id.replace("-", "").replace("_", "").isalnum():
            raise MediaStorageError("invalid media camera identifier")
        if not event_id.replace("-", "").isalnum():
            raise MediaStorageError("invalid media event identifier")
        target = self.root / camera_id / f"{event_id}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def save_snapshot(self, camera_id: str, event_id: str, data: bytes) -> StoredMedia:
        return self._atomic_save(self._target(camera_id, event_id, ".jpg"), data)

    def _atomic_save(self, target: Path, data: bytes) -> StoredMedia:
        if len(data) > self.quota_bytes:
            raise MediaStorageError("media exceeds storage quota")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(target)
        except OSError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise MediaStorageError("media storage is unavailable") from error
        removed = self.enforce_quota(protect=target)
        return StoredMedia(str(target.relative_to(self.root)), tuple(removed))

    def save_clip_frames(
        self, camera_id: str, event_id: str, frames: list[Frame], fps: float
    ) -> StoredMedia:
        images = [frame.image for frame in frames if frame.image is not None]
        if not images:
            raise MediaStorageError("clip has no decoded frames")
        try:
            import cv2
        except ImportError as error:
            raise MediaStorageError("clip encoder is unavailable") from error
        cv: Any = cv2
        target = self._target(camera_id, event_id, ".mp4")
        descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, suffix=".mp4")
        os.close(descriptor)
        temporary = Path(temporary_name)
        height, width = images[0].shape[:2]
        writer = cv.VideoWriter(
            str(temporary), cv.VideoWriter_fourcc(*"mp4v"), max(fps, 1), (width, height)
        )
        try:
            if not writer.isOpened():
                raise MediaStorageError("clip encoder could not start")
            for image in images:
                if image.shape[:2] != (height, width):
                    image = cv.resize(image, (width, height))
                writer.write(image)
        except OSError as error:
            raise MediaStorageError("media storage is unavailable") from error
        finally:
            writer.release()
        try:
            if temporary.stat().st_size > self.quota_bytes:
                raise MediaStorageError("media exceeds storage quota")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        removed = self.enforce_quota(protect=target)
        return StoredMedia(str(target.relative_to(self.root)), tuple(removed))

    def enforce_quota(self, protect: Path | None = None) -> list[str]:
        files = [item for item in self.root.rglob("*") if item.is_file()]
        total = sum(item.stat().st_size for item in files)
        removed: list[str] = []
        for item in sorted(files, key=lambda path: path.stat().st_mtime_ns):
            if total <= self.quota_bytes:
                break
            if protect is not None and item == protect:
                continue
            size = item.stat().st_size
            item.unlink(missing_ok=True)
            total -= size
            removed.append(str(item.relative_to(self.root)))
        if total > self.quota_bytes and protect is not None:
            protect.unlink(missing_ok=True)
            raise MediaStorageError("media storage quota is exhausted")
        return removed

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise FileNotFoundError("media not found")
        return candidate

    def delete(self, relative_paths: tuple[str | None, ...]) -> None:
        for relative in relative_paths:
            if not relative:
                continue
            try:
                self.resolve(relative).unlink(missing_ok=True)
            except FileNotFoundError:
                continue


@dataclass
class ClipSession:
    event_id: str
    camera_id: str
    frames: list[Frame]
    triggered_at: float
    post_roll_seconds: float


ClipComplete = Callable[[str, StoredMedia], Awaitable[None]]
ClipFailed = Callable[[str], Awaitable[None]]
ClipSaver = Callable[[str, str, list[Frame], float], StoredMedia]


class ClipRecorder:
    def __init__(
        self,
        store: MediaStore,
        *,
        fps: float,
        duration_seconds: float,
        pre_roll_seconds: float,
        on_complete: ClipComplete,
        on_failed: ClipFailed,
        save_clip: ClipSaver | None = None,
    ) -> None:
        self.store = store
        self.fps = fps
        self.duration_seconds = duration_seconds
        self.pre_roll_seconds = min(pre_roll_seconds, duration_seconds)
        self.on_complete = on_complete
        self.on_failed = on_failed
        self.save_clip = save_clip or store.save_clip_frames
        self.buffer: deque[Frame] = deque(maxlen=max(1, round(fps * self.pre_roll_seconds)))
        self.sessions: dict[str, ClipSession] = {}
        self.tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _copy(frame: Frame) -> Frame:
        image: Any | None = frame.image
        copied = image.copy() if image is not None and hasattr(image, "copy") else image
        return Frame(frame.width, frame.height, frame.capture_timestamp, copied)

    def observe(self, frame: Frame) -> None:
        if frame.image is None:
            return
        copied = self._copy(frame)
        self.buffer.append(copied)
        completed: list[ClipSession] = []
        timestamp = frame.capture_timestamp.timestamp()
        for session in self.sessions.values():
            session.frames.append(copied)
            if timestamp - session.triggered_at >= session.post_roll_seconds:
                completed.append(session)
        for session in completed:
            self.sessions.pop(session.event_id, None)
            self._schedule(session)

    def trigger(self, event_id: str, camera_id: str) -> bool:
        if not self.buffer or event_id in self.sessions:
            return False
        triggered_at = self.buffer[-1].capture_timestamp.timestamp()
        self.sessions[event_id] = ClipSession(
            event_id,
            camera_id,
            list(self.buffer),
            triggered_at,
            max(0, self.duration_seconds - self.pre_roll_seconds),
        )
        return True

    def start_manual(self, event_id: str, camera_id: str) -> None:
        if any(item.post_roll_seconds == float("inf") for item in self.sessions.values()):
            raise MediaStorageError("manual recording is already active")
        timestamp = self.buffer[-1].capture_timestamp.timestamp() if self.buffer else 0
        self.sessions[event_id] = ClipSession(event_id, camera_id, [], timestamp, float("inf"))

    def stop_manual(self, event_id: str) -> bool:
        session = self.sessions.pop(event_id, None)
        if session is None:
            return False
        self._schedule(session)
        return True

    def _schedule(self, session: ClipSession) -> None:
        task = asyncio.create_task(self._finish(session))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _finish(self, session: ClipSession) -> None:
        try:
            stored = await asyncio.to_thread(
                self.save_clip,
                session.camera_id,
                session.event_id,
                session.frames,
                self.fps,
            )
            await self.on_complete(session.event_id, stored)
        except Exception:
            await self.on_failed(session.event_id)

    async def close(self) -> None:
        for event_id in list(self.sessions):
            session = self.sessions.pop(event_id)
            if session.frames:
                self._schedule(session)
        if self.tasks:
            await asyncio.gather(*self.tasks)
