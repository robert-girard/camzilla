from app.config import Settings
from app.validation import missing_configuration


def test_validation_reports_name_not_secret() -> None:
    assert missing_configuration(Settings()) == ["CAMZILLA_CAMERA_RTSP_URL"]


def test_validation_accepts_camera_url_without_exposing_it() -> None:
    settings = Settings(camera_rtsp_url="rtsp://camera.local/stream")
    assert missing_configuration(settings) == []
