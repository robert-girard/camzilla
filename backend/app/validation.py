from .config import Settings

REQUIRED_FOR_CAMERA = ("CAMZILLA_CAMERA_RTSP_URL",)


def missing_configuration(settings: Settings) -> list[str]:
    """Return variable names only; values, including URLs, are never rendered."""
    return [name for name in REQUIRED_FOR_CAMERA if not settings.camera_rtsp_url]
