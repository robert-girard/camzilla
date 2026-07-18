"""Managed model provenance and local artifact verification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    sha256: str


@dataclass(frozen=True)
class ArtifactStatus:
    verified: bool
    reason: str | None
    path: Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_model_manifest(path: Path) -> dict[str, ModelRecord]:
    """Parse the repository's deliberately scalar-only YAML manifest."""
    records: dict[str, ModelRecord] = {}
    current_id: str | None = None
    current_sha: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("- id:"):
            if current_id and current_sha:
                records[current_id] = ModelRecord(current_id, current_sha)
            current_id = line.split(":", 1)[1].strip()
            current_sha = None
        elif current_id and line.startswith("sha256:"):
            current_sha = line.split(":", 1)[1].strip()
    if current_id and current_sha:
        records[current_id] = ModelRecord(current_id, current_sha)
    return records


class ModelRegistry:
    def __init__(self, manifest_path: Path, model_directory: Path) -> None:
        self.records = read_model_manifest(manifest_path)
        self.model_directory = model_directory

    def artifact_status(self, model_id: str, override: Path | None = None) -> ArtifactStatus:
        path = override or self.model_directory / f"{model_id}.pt"
        record = self.records.get(model_id)
        if record is None:
            return ArtifactStatus(False, "model provenance is unavailable", path)
        if not path.is_file():
            return ArtifactStatus(False, "model artifact is not installed", path)
        try:
            verified = file_sha256(path) == record.sha256
        except OSError:
            return ArtifactStatus(False, "model artifact cannot be read", path)
        if not verified:
            return ArtifactStatus(False, "model artifact checksum does not match", path)
        return ArtifactStatus(True, None, path)
