from pathlib import Path

from app.config import SUPPORTED_MODEL_IDS


def parse_manifest_ids() -> set[str]:
    manifest = Path(__file__).parents[2] / "models" / "manifest.yaml"
    return {
        line.split(":", 1)[1].strip()
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- id:")
    }


def test_every_supported_model_has_provenance() -> None:
    assert parse_manifest_ids() == SUPPORTED_MODEL_IDS
