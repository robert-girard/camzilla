from pathlib import Path

from .config import Settings

REQUIRED_FOR_CAMERA = ("CAMZILLA_CAMERA_RTSP_URL",)


def missing_configuration(settings: Settings, *, require_camera: bool = False) -> list[str]:
    """Return variable names only; values, including URLs, are never rendered."""
    missing: list[str] = []
    if require_camera and not settings.camera_rtsp_url:
        missing.extend(REQUIRED_FOR_CAMERA)
    if (
        settings.inference_backend == "ultralytics"
        and not Path(settings.resolved_model_path).is_file()
    ):
        missing.append("CAMZILLA_MODEL_PATH")
    return missing
