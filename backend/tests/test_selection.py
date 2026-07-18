import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.contracts import InferenceCapability
from app.inference import DetectionWorker, FakeInferenceBackend, Frame
from app.model_registry import ModelRegistry
from app.pipeline import InferencePipeline
from app.selection import (
    CapabilitySpec,
    InferenceSelectionService,
    SelectionError,
    build_capability_specs,
    capability_id,
)
from app.transport import DetectionHub


class TrackingBackend(FakeInferenceBackend):
    def __init__(
        self,
        model_id: str,
        *,
        fail_load: bool = False,
        load_counter: dict[str, int] | None = None,
    ) -> None:
        super().__init__(model_id, "cpu", "cpu")
        self.fail_load = fail_load
        self.closed = 0
        self.load_counter = load_counter

    async def load(self) -> None:
        if self.load_counter is not None:
            self.load_counter["active"] += 1
            self.load_counter["maximum"] = max(
                self.load_counter["maximum"], self.load_counter["active"]
            )
            await asyncio.sleep(0.01)
            self.load_counter["active"] -= 1
        if self.fail_load:
            raise RuntimeError("private candidate failure details")
        await super().load()

    async def close(self) -> None:
        self.closed += 1
        await super().close()


def available_spec(model_id: str) -> CapabilitySpec:
    capability = InferenceCapability(
        id=capability_id("fake", model_id, "cpu"),
        backend_id="fake",
        model_id=model_id,
        target="cpu",
        device="cpu",
        compatible=True,
        available=True,
    )
    return CapabilitySpec(capability)


async def make_service(
    candidates: dict[str, TrackingBackend],
) -> tuple[InferenceSelectionService, TrackingBackend, DetectionWorker, DetectionHub]:
    initial = TrackingBackend("initial")
    await initial.load()
    hub = DetectionHub()
    worker = DetectionWorker(initial, frozenset({"person"}), 0.5, hub.publish)
    pipeline = InferencePipeline(worker)
    specs = {
        capability_id("fake", model_id, "cpu"): available_spec(model_id)
        for model_id in ("initial", *candidates)
    }
    service = InferenceSelectionService(
        specs,
        capability_id("fake", "initial", "cpu"),
        await initial.health(),
        worker,
        pipeline,
        hub,
        lambda spec: candidates[spec.capability.model_id],
    )
    return service, initial, worker, hub


@pytest.mark.asyncio
async def test_successful_switch_resets_results_and_closes_previous_backend() -> None:
    candidate = TrackingBackend("candidate")
    service, initial, worker, hub = await make_service({"candidate": candidate})
    await worker.process(Frame(640, 480, datetime.now(UTC)))
    assert hub.last_message is not None
    assert worker.sequence == 1

    response = await service.select(capability_id("fake", "candidate", "cpu"))

    assert response.active.model_id == "candidate"
    assert response.transition_state == "ready"
    assert worker.backend is candidate
    assert worker.sequence == 0
    assert hub.last_message is None
    assert initial.closed == 1


@pytest.mark.asyncio
async def test_failed_switch_keeps_previous_backend_and_redacts_failure() -> None:
    candidate = TrackingBackend("broken", fail_load=True)
    service, initial, worker, _hub = await make_service({"broken": candidate})

    with pytest.raises(SelectionError, match="previous inference remains active") as error:
        await service.select(capability_id("fake", "broken", "cpu"))

    assert "private candidate" not in str(error.value)
    assert worker.backend is initial
    assert service.transition_state == "degraded"
    assert candidate.closed == 1
    assert initial.closed == 0


@pytest.mark.asyncio
async def test_concurrent_switches_are_serialized() -> None:
    counter = {"active": 0, "maximum": 0}
    candidates = {
        model_id: TrackingBackend(model_id, load_counter=counter)
        for model_id in ("first", "second")
    }
    service, _initial, _worker, _hub = await make_service(candidates)

    await asyncio.gather(
        service.select(capability_id("fake", "first", "cpu")),
        service.select(capability_id("fake", "second", "cpu")),
    )

    assert counter["maximum"] == 1
    assert service.response().active.model_id == "second"


@pytest.mark.asyncio
async def test_unknown_and_unavailable_capabilities_are_rejected() -> None:
    candidate = TrackingBackend("candidate")
    service, _initial, _worker, _hub = await make_service({"candidate": candidate})
    unavailable = InferenceCapability(
        id="rknn:unconfigured:npu",
        backend_id="rknn",
        model_id="unconfigured",
        target="npu",
        device="npu",
        compatible=False,
        available=False,
        unavailable_reason="NPU runtime is not configured",
    )
    service.specs[unavailable.id] = CapabilitySpec(unavailable)

    with pytest.raises(SelectionError) as missing:
        await service.select("fake:missing:cpu")
    assert missing.value.kind == "not_found"
    with pytest.raises(SelectionError) as blocked:
        await service.select(unavailable.id)
    assert blocked.value.kind == "unavailable"


def write_manifest(directory: Path, model_id: str, content: bytes) -> ModelRegistry:
    directory.mkdir()
    checksum = hashlib.sha256(content).hexdigest()
    manifest = directory / "manifest.yaml"
    manifest.write_text(f"models:\n  - id: {model_id}\n    sha256: {checksum}\n", encoding="utf-8")
    (directory / f"{model_id}.pt").write_bytes(content)
    return ModelRegistry(manifest, directory)


def test_capabilities_require_verified_artifacts_and_report_all_targets(tmp_path) -> None:
    registry = write_manifest(tmp_path / "models", "yolov8n", b"verified fixture")
    specs = build_capability_specs(registry, runtime_available=True, cuda_available=False)

    cpu = specs["ultralytics:yolov8n:cpu"].capability
    gpu = specs["ultralytics:yolov8n:gpu"].capability
    assert cpu.available
    assert not gpu.available
    assert gpu.unavailable_reason == "CUDA device is not available"
    assert specs["rknn:unconfigured:npu"].capability.target == "npu"
    assert specs["tpu:unconfigured:tpu"].capability.target == "tpu"
    assert not specs["ultralytics:yolo11m:cpu"].capability.available


def test_checksum_mismatch_is_unavailable_without_exposing_a_path(tmp_path) -> None:
    registry = write_manifest(tmp_path / "models", "yolov8n", b"verified fixture")
    (tmp_path / "models" / "yolov8n.pt").write_bytes(b"tampered")

    capability = build_capability_specs(registry, runtime_available=True, cuda_available=True)[
        "ultralytics:yolov8n:cpu"
    ].capability

    assert not capability.available
    assert capability.unavailable_reason == "model artifact checksum does not match"
    assert str(tmp_path) not in capability.model_dump_json()
