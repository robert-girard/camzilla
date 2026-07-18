import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.inference import Frame
from app.media import ClipRecorder, MediaStorageError, MediaStore, StoredMedia


class Image:
    shape = (10, 10, 3)

    def __init__(self, value=0):
        self.value = value

    def copy(self):
        return Image(self.value)


def frame(second: int) -> Frame:
    return Frame(
        10,
        10,
        datetime(2026, 7, 17, tzinfo=UTC) + timedelta(seconds=second),
        Image(second),
    )


def test_media_store_writes_atomically_and_removes_oldest_at_quota(tmp_path) -> None:
    store = MediaStore(tmp_path, quota_bytes=10)
    first = store.save_snapshot("front-door", "first", b"123456")
    first_path = store.resolve(first.path)
    first_path.touch()
    second = store.save_snapshot("front-door", "second", b"abcdef")

    assert second.removed_paths == ("front-door/first.jpg",)
    assert not first_path.exists()
    assert store.resolve(second.path).read_bytes() == b"abcdef"
    assert not list(tmp_path.rglob("tmp*"))


def test_media_store_rejects_oversize_and_path_traversal(tmp_path) -> None:
    store = MediaStore(tmp_path, quota_bytes=4)
    with pytest.raises(MediaStorageError, match="quota"):
        store.save_snapshot("front-door", "event", b"12345")
    with pytest.raises(FileNotFoundError):
        store.resolve("../private")


def test_media_store_redacts_disk_failure(monkeypatch, tmp_path) -> None:
    store = MediaStore(tmp_path, quota_bytes=100)

    def fail(*_args, **_kwargs):
        raise OSError("private mount details")

    monkeypatch.setattr("app.media.tempfile.NamedTemporaryFile", fail)
    with pytest.raises(MediaStorageError) as caught:
        store.save_snapshot("front-door", "event", b"image")
    assert "private" not in str(caught.value)


@pytest.mark.asyncio
async def test_clip_recorder_includes_pre_roll_and_finishes_after_bounded_duration(
    tmp_path,
) -> None:
    completed = []
    failures = []
    saved_frames = []

    def save(_camera, event_id, frames, _fps):
        saved_frames.extend(item.image.value for item in frames)
        return StoredMedia(f"front-door/{event_id}.mp4", ())

    async def complete(event_id, stored):
        completed.append((event_id, stored.path))

    async def failed(event_id):
        failures.append(event_id)

    recorder = ClipRecorder(
        MediaStore(tmp_path, quota_bytes=100),
        fps=1,
        duration_seconds=5,
        pre_roll_seconds=2,
        on_complete=complete,
        on_failed=failed,
        save_clip=save,
    )
    recorder.observe(frame(0))
    recorder.observe(frame(1))
    assert recorder.trigger("event", "front-door")
    recorder.observe(frame(2))
    recorder.observe(frame(3))
    recorder.observe(frame(4))
    if recorder.tasks:
        await asyncio.gather(*recorder.tasks)

    assert saved_frames == [0, 1, 2, 3, 4]
    assert completed == [("event", "front-door/event.mp4")]
    assert failures == []


@pytest.mark.asyncio
async def test_manual_recording_is_singleton_and_stops_through_same_encoder(tmp_path) -> None:
    completed = []

    def save(_camera, event_id, frames, _fps):
        return StoredMedia(f"front-door/{event_id}.mp4", ())

    async def complete(event_id, _stored):
        completed.append(event_id)

    async def failed(_event_id):
        raise AssertionError("encoding should not fail")

    recorder = ClipRecorder(
        MediaStore(tmp_path, quota_bytes=100),
        fps=1,
        duration_seconds=5,
        pre_roll_seconds=1,
        on_complete=complete,
        on_failed=failed,
        save_clip=save,
    )
    recorder.start_manual("manual-one", "front-door")
    with pytest.raises(MediaStorageError, match="already active"):
        recorder.start_manual("manual-two", "front-door")
    recorder.observe(frame(1))
    assert recorder.stop_manual("manual-one")
    await recorder.close()
    assert completed == ["manual-one"]


def test_production_opencv_encoder_writes_a_playable_container_when_available(tmp_path) -> None:
    pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    store = MediaStore(tmp_path, quota_bytes=1024 * 1024)
    frames = [
        Frame(
            64,
            48,
            datetime(2026, 7, 17, tzinfo=UTC) + timedelta(seconds=index / 5),
            numpy.zeros((48, 64, 3), dtype=numpy.uint8),
        )
        for index in range(10)
    ]
    stored = store.save_clip_frames("front-door", "event", frames, 5)
    path = store.resolve(stored.path)
    assert path.suffix == ".mp4"
    assert path.stat().st_size > 0
