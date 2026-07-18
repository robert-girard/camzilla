from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_MODEL_IDS = frozenset({"yolov8n", "yolov8s", "yolov8m", "yolo11n", "yolo11s", "yolo11m"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CAMZILLA_", extra="ignore")

    camera_name: str = "front-door"
    camera_rtsp_url: str | None = None
    inference_restream_url: str = "rtsp://go2rtc:8554/front-door"
    inference_backend: str = "fake"
    inference_device: str = "auto"
    model_id: str = "yolov8n"
    model_path: str | None = None
    model_directory: str = "/models"
    model_manifest_path: str | None = None
    inference_fps: float = Field(default=5.0, gt=0, le=60)
    confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    allowed_classes: str = "person"
    result_ttl_seconds: float = Field(default=2.0, gt=0)
    ptz_enabled: bool = False
    ptz_verified: bool = False
    onvif_host: str | None = None
    onvif_port: int = Field(default=8000, ge=1, le=65535)
    onvif_user: str | None = None
    onvif_password: str | None = None
    onvif_profile: str = "PROFILE_000"
    alerts_enabled: bool = True
    alert_classes: str = "person"
    alert_confidence_threshold: float = Field(default=0.6, ge=0, le=1)
    alert_debounce_seconds: float = Field(default=300, ge=1, le=86400)
    notifier: str = "dry-run"
    discord_webhook_url: SecretStr | None = None
    discord_delivery_confirmed: bool = False
    stream_down_alerts_enabled: bool = True
    stream_down_repeat_seconds: float = Field(default=3600, ge=60, le=86400)
    database_url: str = "sqlite+pysqlite:///:memory:"
    media_root: str = "/media"
    media_quota_bytes: int = Field(default=5 * 1024 * 1024 * 1024, ge=1024 * 1024)

    @field_validator("inference_backend")
    @classmethod
    def valid_backend(cls, value: str) -> str:
        if value not in {"fake", "ultralytics"}:
            raise ValueError("must be fake or ultralytics")
        return value

    @field_validator("camera_rtsp_url", mode="before")
    @classmethod
    def blank_camera_url_is_not_configured(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("inference_device")
    @classmethod
    def valid_device(cls, value: str) -> str:
        if value not in {"auto", "cpu", "cuda"}:
            raise ValueError("must be auto, cpu, or cuda")
        return value

    @field_validator("model_id")
    @classmethod
    def valid_model_id(cls, value: str) -> str:
        if value not in SUPPORTED_MODEL_IDS:
            supported = ", ".join(sorted(SUPPORTED_MODEL_IDS))
            raise ValueError(f"must be one of: {supported}")
        return value

    @field_validator("notifier")
    @classmethod
    def valid_notifier(cls, value: str) -> str:
        if value not in {"dry-run", "discord"}:
            raise ValueError("must be dry-run or discord")
        return value

    @property
    def resolved_model_path(self) -> str:
        return self.model_path or f"/models/{self.model_id}.pt"

    @property
    def resolved_model_directory(self) -> Path:
        configured = Path(self.model_directory)
        if configured.exists():
            return configured
        return Path(__file__).resolve().parents[2] / "models"

    @property
    def resolved_model_manifest_path(self) -> Path:
        if self.model_manifest_path:
            return Path(self.model_manifest_path)
        configured = self.resolved_model_directory / "manifest.yaml"
        if configured.exists():
            return configured
        return Path(__file__).resolve().parents[2] / "models" / "manifest.yaml"

    @property
    def class_filter(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.allowed_classes.split(",") if item.strip())

    @property
    def alert_class_filter(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.alert_classes.split(",") if item.strip())

    @property
    def ptz_configuration_complete(self) -> bool:
        return all((self.onvif_host, self.onvif_user, self.onvif_password, self.onvif_profile))


@lru_cache
def get_settings() -> Settings:
    return Settings()
