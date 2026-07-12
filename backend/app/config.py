from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CAMZILLA_", extra="ignore")

    camera_name: str = "front-door"
    camera_rtsp_url: str | None = None
    inference_backend: str = "fake"
    model_id: str = "yolov8n"
    confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    allowed_classes: str = "person"
    result_ttl_seconds: float = Field(default=2.0, gt=0)

    @field_validator("inference_backend")
    @classmethod
    def valid_backend(cls, value: str) -> str:
        if value not in {"fake", "ultralytics"}:
            raise ValueError("must be fake or ultralytics")
        return value

    @property
    def class_filter(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.allowed_classes.split(",") if item.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
