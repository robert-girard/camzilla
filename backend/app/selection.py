"""Capability-driven, transactional inference backend selection."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from .config import SUPPORTED_MODEL_IDS
from .contracts import (
    InferenceCapabilitiesResponse,
    InferenceCapability,
    InferenceSelection,
    InferenceTarget,
    TransitionState,
)
from .inference import BackendHealth, DetectionWorker, InferenceBackend
from .model_registry import ModelRegistry
from .pipeline import InferencePipeline
from .transport import DetectionHub


def capability_id(backend_id: str, model_id: str, target: InferenceTarget) -> str:
    return f"{backend_id}:{model_id}:{target}"


@dataclass(frozen=True)
class CapabilitySpec:
    capability: InferenceCapability
    model_path: str | None = None
    requested_device: str = "cpu"


class SelectionError(Exception):
    def __init__(self, kind: str, public_message: str) -> None:
        super().__init__(public_message)
        self.kind = kind
        self.public_message = public_message


def build_capability_specs(
    registry: ModelRegistry,
    *,
    runtime_available: bool,
    cuda_available: bool,
    include_fake: bool = False,
) -> dict[str, CapabilitySpec]:
    specs: dict[str, CapabilitySpec] = {}
    if include_fake:
        fake = InferenceCapability(
            id=capability_id("fake", "fake-person-v1", "cpu"),
            backend_id="fake",
            model_id="fake-person-v1",
            target="cpu",
            device="synthetic",
            compatible=True,
            available=True,
        )
        specs[fake.id] = CapabilitySpec(fake, requested_device="synthetic")

    for model_id in sorted(SUPPORTED_MODEL_IDS):
        artifact = registry.artifact_status(model_id)
        cpu_reason = artifact.reason if not artifact.verified else None
        if not runtime_available:
            cpu_reason = "Ultralytics runtime is not installed"
        cpu = InferenceCapability(
            id=capability_id("ultralytics", model_id, "cpu"),
            backend_id="ultralytics",
            model_id=model_id,
            target="cpu",
            device="cpu",
            compatible=True,
            available=runtime_available and artifact.verified,
            unavailable_reason=cpu_reason,
        )
        specs[cpu.id] = CapabilitySpec(cpu, str(artifact.path), "cpu")

        gpu_reason = cpu_reason
        if gpu_reason is None and not cuda_available:
            gpu_reason = "CUDA device is not available"
        gpu = InferenceCapability(
            id=capability_id("ultralytics", model_id, "gpu"),
            backend_id="ultralytics",
            model_id=model_id,
            target="gpu",
            device="cuda",
            compatible=True,
            available=runtime_available and artifact.verified and cuda_available,
            unavailable_reason=gpu_reason,
        )
        specs[gpu.id] = CapabilitySpec(gpu, str(artifact.path), "cuda")

    unavailable_specs: tuple[tuple[str, str, InferenceTarget, str], ...] = (
        ("rknn", "unconfigured", "npu", "RKNN NPU support is delivered in Phase 4b"),
        ("tpu", "unconfigured", "tpu", "TPU hardware and runtime are not configured"),
    )
    for backend_id, model_id, target, reason in unavailable_specs:
        capability = InferenceCapability(
            id=capability_id(backend_id, model_id, target),
            backend_id=backend_id,
            model_id=model_id,
            target=target,
            device=target,
            compatible=False,
            available=False,
            unavailable_reason=reason,
        )
        specs[capability.id] = CapabilitySpec(capability, requested_device=target)
    return specs


BackendFactory = Callable[[CapabilitySpec], InferenceBackend]


class InferenceSelectionService:
    def __init__(
        self,
        specs: dict[str, CapabilitySpec],
        active_capability_id: str,
        active_health: BackendHealth,
        worker: DetectionWorker,
        pipeline: InferencePipeline,
        hub: DetectionHub,
        backend_factory: BackendFactory,
    ) -> None:
        if active_capability_id not in specs:
            raise RuntimeError("active inference capability is not registered")
        self.specs = specs
        self.active_capability_id = active_capability_id
        self.active_device = active_health.device
        self.worker = worker
        self.pipeline = pipeline
        self.hub = hub
        self.backend_factory = backend_factory
        self.transition_state: TransitionState = "ready"
        self.transition_error: str | None = None
        self._switch_lock = asyncio.Lock()

    def response(self) -> InferenceCapabilitiesResponse:
        active_spec = self.specs[self.active_capability_id].capability
        active = InferenceSelection(
            capability_id=active_spec.id,
            backend_id=active_spec.backend_id,
            model_id=active_spec.model_id,
            target=active_spec.target,
            device=self.active_device,
        )
        capabilities = [
            spec.capability.model_copy(
                update={"active": spec.capability.id == active.capability_id}
            )
            for spec in self.specs.values()
        ]
        return InferenceCapabilitiesResponse(
            active=active,
            transition_state=self.transition_state,
            transition_error=self.transition_error,
            capabilities=capabilities,
        )

    async def select(self, requested_id: str) -> InferenceCapabilitiesResponse:
        async with self._switch_lock:
            spec = self.specs.get(requested_id)
            if spec is None:
                raise SelectionError("not_found", "inference capability not found")
            if not spec.capability.available or not spec.capability.compatible:
                raise SelectionError("unavailable", "inference capability is unavailable")
            if requested_id == self.active_capability_id:
                self.transition_state = "ready"
                self.transition_error = None
                return self.response()

            self.transition_state = "switching"
            self.transition_error = None
            self.pipeline.pause()
            try:
                candidate = self.backend_factory(spec)
                try:
                    await candidate.load()
                    health = await candidate.health()
                    if (
                        not health.ready
                        or health.backend_id != spec.capability.backend_id
                        or health.model_id != spec.capability.model_id
                        or health.target != spec.capability.target
                    ):
                        raise RuntimeError("candidate identity or health did not match")
                except Exception as error:
                    with suppress(Exception):
                        await candidate.close()
                    self.transition_state = "degraded"
                    self.transition_error = "switch failed; previous inference remains active"
                    raise SelectionError("failed", self.transition_error) from error
                try:
                    previous = await self.worker.replace_backend(candidate)
                except Exception as error:
                    with suppress(Exception):
                        await candidate.close()
                    self.transition_state = "degraded"
                    self.transition_error = "switch failed; previous inference remains active"
                    raise SelectionError("failed", self.transition_error) from error

                self.pipeline.reset()
                await self.hub.reset()
                self.active_capability_id = requested_id
                self.active_device = health.device
                try:
                    await previous.close()
                except Exception:
                    self.transition_state = "degraded"
                    self.transition_error = "previous inference cleanup failed"
                    return self.response()
                self.transition_state = "ready"
                return self.response()
            finally:
                self.pipeline.resume()
