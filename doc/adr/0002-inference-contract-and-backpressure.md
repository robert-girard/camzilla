# ADR 0002: Pluggable inference worker contract

## Status

Accepted — 2026-07-11.

## Decision

Inference backends expose explicit load, detect, health, and close lifecycle
operations and return normalized boxes, source dimensions, timestamps, timing,
backend identity, and model identity. The sampler hands work to a bounded,
latest-frame-wins queue. A deterministic fake backend is the first adapter.

## Consequences

Slow inference drops superseded work rather than raising end-to-end latency.
Loaded CUDA/RKNN runtimes are isolated in an explicitly started process/service
and are never assumed fork-safe. Ultralytics and RKNN must pass the same
contract tests.
