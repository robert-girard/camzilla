import hashlib
import runpy
from pathlib import Path


def test_verified_model_is_readable_by_the_non_root_runtime(tmp_path) -> None:
    repository = tmp_path / "repository"
    models = repository / "models"
    models.mkdir(parents=True)
    content = b"public model fixture"
    checksum = hashlib.sha256(content).hexdigest()
    (models / "manifest.yaml").write_text(
        f"models:\n  - id: fixture\n    sha256: {checksum}\n", encoding="utf-8"
    )
    destination = models / "fixture.pt"
    destination.write_bytes(content)
    destination.chmod(0o600)
    script = Path(__file__).parents[2] / "scripts" / "download-model.py"
    download_model = runpy.run_path(str(script))["download_model"]

    result = download_model("fixture", repository)

    assert result == destination
    assert destination.stat().st_mode & 0o044 == 0o044
