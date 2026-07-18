import asyncio
from datetime import UTC, datetime

import pytest

from app.inference import DetectionWorker, FakeInferenceBackend, Frame
from app.pipeline import InferencePipeline, ReconnectingFrameSource


@pytest.mark.asyncio
async def test_pipeline_drops_superseded_frames_when_inference_is_slow() -> None:
    messages = []

    async def publish(message):
        messages.append(message)

    class SlowFake(FakeInferenceBackend):
        async def detect(self, frame):
            await asyncio.sleep(0.02)
            return await super().detect(frame)

    backend = SlowFake()
    await backend.load()
    worker = DetectionWorker(backend, frozenset({"coco:person"}), 0.5, publish)
    pipeline = InferencePipeline(worker, source_dropped_frames=lambda: 2)

    async def source():
        for _ in range(5):
            yield Frame(640, 480, datetime.now(UTC))

    await pipeline.start(source())
    await asyncio.sleep(0.06)
    await pipeline.close()
    assert pipeline.queue.dropped >= 3
    assert pipeline.dropped_frames == pipeline.queue.dropped + 2
    assert worker.processed_frames < 5
    assert messages


@pytest.mark.asyncio
async def test_source_failure_is_redacted_and_pipeline_closes_cleanly() -> None:
    async def publish(_message):
        return None

    backend = FakeInferenceBackend()
    await backend.load()
    worker = DetectionWorker(backend, frozenset({"coco:person"}), 0.5, publish)
    pipeline = InferencePipeline(worker)

    async def broken_source():
        if False:
            yield Frame(640, 480, datetime.now(UTC))
        raise RuntimeError("private camera source details")

    await pipeline.start(broken_source())
    await asyncio.sleep(0)
    assert pipeline.source_error == "RuntimeError"
    await pipeline.close()
    assert pipeline._producer is not None and pipeline._producer.done()
    assert pipeline._consumer is not None and pipeline._consumer.done()


@pytest.mark.asyncio
async def test_reconnecting_source_reports_redacted_transitions_and_recovers() -> None:
    attempts = 0
    sleeps = []
    transitions = []

    async def source():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("private restream URL")
        yield Frame(640, 480, datetime.now(UTC))

    async def no_sleep(delay):
        sleeps.append(delay)

    reconnecting = ReconnectingFrameSource(
        source,
        on_state=transitions.append,
        initial_delay=0.25,
        sleep=no_sleep,
    )
    frames = reconnecting.frames()
    frame = await anext(frames)
    await frames.aclose()

    assert frame.width == 640
    assert sleeps == [0.25]
    assert transitions == ["degraded", "connecting", "ready"]
    assert reconnecting.status.reconnects == 1
    assert reconnecting.status.last_error is None
    assert "private" not in repr(reconnecting.status)


@pytest.mark.asyncio
async def test_inference_failure_does_not_terminate_pipeline_consumer() -> None:
    published = []

    async def publish(message):
        published.append(message)

    class FailOnceBackend(FakeInferenceBackend):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def detect(self, frame):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient runtime failure")
            return await super().detect(frame)

    backend = FailOnceBackend()
    await backend.load()
    worker = DetectionWorker(backend, frozenset({"coco:person"}), 0.5, publish)
    pipeline = InferencePipeline(worker)

    async def source():
        yield Frame(640, 480, datetime.now(UTC))
        await asyncio.sleep(0.01)
        yield Frame(640, 480, datetime.now(UTC))
        await asyncio.Event().wait()

    await pipeline.start(source())
    await asyncio.sleep(0.04)

    assert worker.failed_frames == 1
    assert worker.processed_frames == 1
    assert pipeline.consumer_error is None
    assert pipeline._consumer is not None and not pipeline._consumer.done()
    assert len(published) == 1
    await pipeline.close()
