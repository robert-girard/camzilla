from copy import deepcopy

import pytest
from sqlalchemy import select

from app.backup import build_backup, validate_backup
from app.contracts import BackupDocument
from app.persistence import (
    CameraRecord,
    ConfigurationConflictError,
    Database,
    Repository,
)


@pytest.fixture
def repository(tmp_path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'camzilla.db'}")
    database.migrate()
    repo = Repository(database)
    repo.seed("front-door", "fake:fake-person-v1:cpu")
    yield repo
    database.close()


def test_backup_export_excludes_secrets_capabilities_and_media(repository) -> None:
    backup = build_backup(repository.configuration())
    payload = backup.model_dump_json()
    assert backup.secrets_included is False
    assert backup.schema_version == "2"
    assert "secret_ref" not in payload.lower()
    assert "CAMZILLA_CAMERA_RTSP_URL" not in payload
    assert "capabilities" not in payload
    assert "events" not in payload
    assert "media" not in payload


def test_backup_validation_redacts_invalid_input() -> None:
    invalid = {
        "schema_version": "unsupported-private-value",
        "exported_at": "not-a-time",
        "secrets_included": True,
        "active_capability_id": "fake:fake-person-v1:cpu",
        "cameras": [],
        "alert_rules": [],
    }
    result = validate_backup(invalid)
    assert result.valid is False
    assert all(item.startswith("invalid field:") for item in result.errors)
    assert "unsupported-private-value" not in result.model_dump_json()


def test_restore_round_trip_preserves_existing_refs_and_derives_new_refs(repository) -> None:
    exported = build_backup(repository.configuration()).model_dump(mode="json")
    changed = deepcopy(exported)
    changed["cameras"].append(
        {
            "id": "side-door",
            "name": "Side door",
            "enabled": True,
            "allowed_categories": ["coco:person"],
            "catalog_revision": "coco-person-v1",
        }
    )
    changed["alert_rules"][0]["confidence_threshold"] = 0.8
    document = BackupDocument.model_validate(changed)
    version = repository.configuration_version()
    next_version = repository.restore_backup(document, expected_config_version=version)

    restored = repository.configuration()
    assert next_version == version + 1
    assert restored.alert_rules[0].confidence_threshold == 0.8
    assert {camera.id for camera in restored.cameras} == {"front-door", "side-door"}
    with repository.database.session() as session:
        records = {item.id: item for item in session.scalars(select(CameraRecord))}
    assert records["front-door"].stream_secret_ref == "env:CAMZILLA_CAMERA_RTSP_URL"
    assert records["side-door"].stream_secret_ref == "env:CAMZILLA_SIDE_DOOR_RTSP_URL"
    with pytest.raises(ConfigurationConflictError):
        repository.restore_backup(document, expected_config_version=version)


def test_person_only_v1_backup_migrates_to_semantic_ids_and_active_catalog() -> None:
    legacy = {
        "schema_version": "1",
        "exported_at": "2026-07-17T12:00:00Z",
        "secrets_included": False,
        "active_capability_id": "ultralytics:yolo11s:cpu",
        "cameras": [
            {
                "id": "front-door",
                "name": "Front door",
                "enabled": True,
                "allowed_categories": ["person"],
                "catalog_revision": "person-v1",
            }
        ],
        "alert_rules": [
            {
                "id": "person-detected",
                "camera_id": "front-door",
                "enabled": True,
                "target_categories": ["person"],
                "confidence_threshold": 0.6,
                "debounce_seconds": 300,
            }
        ],
    }

    migrated = BackupDocument.model_validate(legacy)

    assert migrated.schema_version == "2"
    assert migrated.cameras[0].allowed_categories == ["coco:person"]
    assert migrated.cameras[0].catalog_revision == "coco80-v1"
    assert migrated.alert_rules[0].target_categories == ["coco:person"]
    assert validate_backup(legacy).valid
