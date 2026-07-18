import pytest
from pydantic import ValidationError

from app.config import Settings
from app.validation import missing_configuration


def test_validation_reports_name_not_secret() -> None:
    assert missing_configuration(Settings(), require_camera=True) == ["CAMZILLA_CAMERA_RTSP_URL"]


def test_validation_accepts_no_camera_for_synthetic_development() -> None:
    assert missing_configuration(Settings()) == []


def test_blank_camera_url_uses_synthetic_development() -> None:
    assert Settings(camera_rtsp_url="").camera_rtsp_url is None


def test_validation_accepts_camera_url_without_exposing_it() -> None:
    settings = Settings(camera_rtsp_url="rtsp://camera.local/stream")
    assert missing_configuration(settings, require_camera=True) == []


def test_validation_reports_missing_managed_weight_by_variable_name(tmp_path) -> None:
    settings = Settings(inference_backend="ultralytics", model_path=str(tmp_path / "missing.pt"))
    assert missing_configuration(settings) == ["CAMZILLA_MODEL_PATH"]


@pytest.mark.parametrize(
    "model_id",
    ["yolov8n", "yolov8s", "yolov8m", "yolo11n", "yolo11s", "yolo11m"],
)
def test_supported_model_ids_resolve_to_their_managed_weight(model_id: str) -> None:
    settings = Settings(model_id=model_id)
    assert settings.resolved_model_path == f"/models/{model_id}.pt"


def test_explicit_model_path_is_preserved() -> None:
    settings = Settings(model_id="yolo11s", model_path="/verified/yolo11s.pt")
    assert settings.resolved_model_path == "/verified/yolo11s.pt"


def test_unmanaged_model_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be one of"):
        Settings(model_id="yolo11x")
