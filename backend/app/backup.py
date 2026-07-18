"""Portable, secret-free configuration backup validation."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from .contracts import (
    BackupAlertRule,
    BackupCamera,
    BackupDocument,
    BackupValidationResponse,
    GlobalConfiguration,
)


def build_backup(configuration: GlobalConfiguration) -> BackupDocument:
    return BackupDocument(
        exported_at=datetime.now(UTC),
        active_capability_id=configuration.active_capability_id,
        cameras=[
            BackupCamera(
                id=camera.id,
                name=camera.name,
                enabled=camera.enabled,
                allowed_categories=camera.allowed_categories,
                catalog_revision=camera.catalog_revision,
            )
            for camera in configuration.cameras
        ],
        alert_rules=[
            BackupAlertRule(
                id=rule.id,
                camera_id=rule.camera_id,
                enabled=rule.enabled,
                target_categories=rule.target_categories,
                confidence_threshold=rule.confidence_threshold,
                debounce_seconds=rule.debounce_seconds,
                schedule_start=rule.schedule_start,
                schedule_end=rule.schedule_end,
                zone=rule.zone,
            )
            for rule in configuration.alert_rules
        ],
    )


def validate_backup(document: dict[str, object]) -> BackupValidationResponse:
    try:
        BackupDocument.model_validate(document)
    except ValidationError as error:
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
        return BackupValidationResponse(
            valid=False,
            errors=[f"invalid field: {field}" for field in fields],
        )
    return BackupValidationResponse(valid=True)
