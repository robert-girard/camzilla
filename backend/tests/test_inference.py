from datetime import UTC, datetime

import pytest

from app.inference import DetectionWorker, FakeInferenceBackend, Frame


@pytest.mark.asyncio
async def test_fake_backend_matches_contract_and_filter() -> None:
    published = []

    async def publish(message):
        published.append(message)

    backend = FakeInferenceBackend()
    await backend.load()
    worker = DetectionWorker(backend, frozenset({"person"}), 0.9, publish)
    result = await worker.process(Frame(640, 480, datetime.now(UTC)))
    assert result.detections[0].class_name == "person"
    assert result.source_width == 640
    assert result.sequence == 0
    assert published == [result]


@pytest.mark.asyncio
async def test_confidence_filter_removes_fake_detection() -> None:
    async def publish(_message):
        return None

    backend = FakeInferenceBackend()
    await backend.load()
    worker = DetectionWorker(backend, frozenset({"person"}), 0.99, publish)
    result = await worker.process(Frame(640, 480, datetime.now(UTC)))
    assert result.detections == []
