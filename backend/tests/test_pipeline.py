import asyncio
from datetime import UTC, datetime

import pytest

from app.inference import DetectionWorker, FakeInferenceBackend, Frame
from app.pipeline import InferencePipeline


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
    worker = DetectionWorker(backend, frozenset({"person"}), 0.5, publish)
    pipeline = InferencePipeline(worker)

    async def source():
        for _ in range(5):
            yield Frame(640, 480, datetime.now(UTC))

    await pipeline.start(source())
    await asyncio.sleep(0.06)
    await pipeline.close()
    assert pipeline.dropped_frames >= 3
    assert worker.processed_frames < 5
    assert messages
