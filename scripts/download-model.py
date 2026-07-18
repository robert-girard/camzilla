#!/usr/bin/env python3
"""Download one managed model weight and verify its recorded SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    """Parse the repository's deliberately small, scalar-only model manifest."""
    models: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "models:":
            continue
        if line.startswith("- id:"):
            model_id = line.split(":", 1)[1].strip()
            current = {"id": model_id}
            models[model_id] = current
            continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip()
    return models


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_model(model_id: str, repository: Path) -> Path:
    manifest = read_manifest(repository / "models" / "manifest.yaml")
    if model_id not in manifest:
        choices = ", ".join(sorted(manifest))
        raise ValueError(f"unsupported model {model_id!r}; choose one of: {choices}")

    record = manifest[model_id]
    destination = repository / "models" / f"{model_id}.pt"
    expected = record["sha256"]
    if destination.exists():
        if sha256(destination) == expected:
            return destination
        raise ValueError(
            f"{destination.name} exists but does not match the manifest; remove it explicitly"
        )

    request = urllib.request.Request(
        record["upstream"], headers={"User-Agent": "Camzilla model provenance downloader"}
    )
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=f".{model_id}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            with urllib.request.urlopen(request, timeout=60) as response:
                while block := response.read(1024 * 1024):
                    temporary.write(block)
        temporary_path = Path(temporary_name)
        actual = sha256(temporary_path)
        if actual != expected:
            raise ValueError(
                f"downloaded {model_id} checksum mismatch (expected {expected}, got {actual})"
            )
        os.replace(temporary_path, destination)
        temporary_name = None
        return destination
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download a supported Ultralytics weight and verify its manifest checksum."
    )
    parser.add_argument("model_id")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    try:
        destination = download_model(args.model_id, repository)
    except (OSError, ValueError) as error:
        print(f"Model download failed: {error}", file=sys.stderr)
        return 1
    print(f"Verified model available at {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
