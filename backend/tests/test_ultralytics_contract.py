"""Opt-in contract check using a redistributable public image and local weights.

CI intentionally skips this test: model weights are not repository artifacts.
Run it with CAMZILLA_ULTRALYTICS_MODEL_PATH and
CAMZILLA_ULTRALYTICS_FIXTURE_PATH set to verified local files.
"""

import importlib.util
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.inference import Frame, UltralyticsBackend

MODEL_PATH = os.getenv("CAMZILLA_ULTRALYTICS_MODEL_PATH")
FIXTURE_PATH = os.getenv("CAMZILLA_ULTRALYTICS_FIXTURE_PATH")
ALL_MODELS = os.getenv("CAMZILLA_ULTRALYTICS_ALL_MODELS") == "1"
MODEL_DIRECTORY = Path(__file__).parents[2] / "models"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (
        MODEL_PATH and FIXTURE_PATH and Path(MODEL_PATH).is_file() and Path(FIXTURE_PATH).is_file()
    ),
    reason="set verified local Ultralytics model and redistributable fixture paths to run",
)
async def test_ultralytics_contract_detects_person_from_fixture() -> None:
    if importlib.util.find_spec("cv2") is None:
        pytest.skip("OpenCV is only installed with the Ultralytics runtime extra")
    import cv2

    image = cv2.imread(FIXTURE_PATH)
    assert image is not None
    backend = UltralyticsBackend("yolov8n", MODEL_PATH, "cpu")
    await backend.load()
    try:
        detections = await backend.detect(
            Frame(image.shape[1], image.shape[0], datetime.now(UTC), image)
        )
    finally:
        await backend.close()
    persons = [item for item in detections if item.class_name == "person"]
    assert persons
    assert max(item.confidence for item in persons) >= 0.5


@pytest.mark.asyncio
@pytest.mark.skipif(
    not ALL_MODELS,
    reason="set CAMZILLA_ULTRALYTICS_ALL_MODELS=1 after downloading all managed weights",
)
@pytest.mark.parametrize(
    "model_id",
    ["yolov8n", "yolov8s", "yolov8m", "yolo11n", "yolo11s", "yolo11m"],
)
async def test_all_managed_ultralytics_models_load_and_detect(model_id: str) -> None:
    if importlib.util.find_spec("numpy") is None:
        pytest.skip("NumPy is only installed with the Ultralytics runtime extra")
    import numpy as np

    model_path = MODEL_DIRECTORY / f"{model_id}.pt"
    assert model_path.is_file(), f"download {model_id} with scripts/download-model.py"
    backend = UltralyticsBackend(model_id, str(model_path), "cpu")
    await backend.load()
    try:
        detections = await backend.detect(
            Frame(64, 64, datetime.now(UTC), np.zeros((64, 64, 3), dtype=np.uint8))
        )
        health = await backend.health()
    finally:
        await backend.close()
    assert detections == []
    assert health.ready is True
    assert health.model_id == model_id
    assert health.device == "cpu"
