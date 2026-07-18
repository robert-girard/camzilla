from datetime import UTC, datetime

import pytest

from app.inference import DetectionWorker, FakeInferenceBackend, Frame, select_inference_device


@pytest.mark.asyncio
async def test_fake_backend_matches_contract_and_filter() -> None:
    published = []

    async def publish(message):
        published.append(message)

    backend = FakeInferenceBackend()
    await backend.load()
    worker = DetectionWorker(backend, frozenset({"coco:person"}), 0.9, publish)
    result = await worker.process(Frame(640, 480, datetime.now(UTC)))
    assert result.detections[0].class_name == "person"
    assert result.detections[0].semantic_id == "coco:person"
    assert result.detections[0].native_class_id == 0
    assert result.source_width == 640
    assert result.sequence == 0
    assert result.inference_fps >= 0
    assert published == [result]


@pytest.mark.asyncio
async def test_multi_category_fake_uses_semantic_allowlist_and_metrics() -> None:
    async def publish(_message):
        return None

    backend = FakeInferenceBackend(model_id="fake-multi-v1")
    await backend.load()
    worker = DetectionWorker(backend, frozenset({"coco:person", "coco:car"}), 0.5, publish)

    result = await worker.process(Frame(640, 480, datetime.now(UTC)))

    assert [item.semantic_id for item in result.detections] == ["coco:person", "coco:car"]
    assert worker.published_detections == {"coco:person": 1, "coco:car": 1}


@pytest.mark.asyncio
async def test_confidence_filter_removes_fake_detection() -> None:
    async def publish(_message):
        return None

    backend = FakeInferenceBackend()
    await backend.load()
    worker = DetectionWorker(backend, frozenset({"coco:person"}), 0.99, publish)
    result = await worker.process(Frame(640, 480, datetime.now(UTC)))
    assert result.detections == []


@pytest.mark.asyncio
async def test_inference_failure_is_counted_without_publishing() -> None:
    published = []

    class BrokenFake(FakeInferenceBackend):
        async def detect(self, frame):
            raise RuntimeError("synthetic failure")

    backend = BrokenFake()
    await backend.load()
    worker = DetectionWorker(backend, frozenset({"coco:person"}), 0.5, published.append)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await worker.process(Frame(640, 480, datetime.now(UTC)))
    assert worker.failed_frames == 1
    assert worker.processed_frames == 0
    assert published == []


def test_cuda_selection_reports_an_explicit_cpu_fallback() -> None:
    assert select_inference_device("cuda", False) == (
        "cpu",
        "CUDA requested but unavailable; using CPU",
    )
    assert select_inference_device("auto", False) == ("cpu", "CUDA unavailable; using CPU")
    assert select_inference_device("auto", True) == ("cuda", None)
