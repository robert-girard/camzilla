"""SQLAlchemy persistence boundary for local single-node configuration and events."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class ConfigState(Base):
    __tablename__ = "config_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_capability_id: Mapped[str] = mapped_column(String(160), nullable=False)
    notifier_secret_ref: Mapped[str] = mapped_column(
        String(160), nullable=False, default="env:CAMZILLA_DISCORD_WEBHOOK_URL"
    )


class CameraRecord(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stream_secret_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    allowed_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    catalog_revision: Mapped[str] = mapped_column(String(120), nullable=False, default="person-v1")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AlertRuleRecord(Base):
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    target_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    debounce_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=300)
    schedule_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    schedule_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    zone: Mapped[list[list[float]] | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), nullable=False, index=True)
    rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("alert_rules.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    snapshot_path: Mapped[str | None] = mapped_column(String(240), nullable=True)
    clip_path: Mapped[str | None] = mapped_column(String(240), nullable=True)


class ConfigurationConflictError(Exception):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        arguments: dict[str, Any] = {}
        if url.startswith("sqlite"):
            arguments["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            arguments["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, **arguments)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self) -> None:
        if ":memory:" in self.url:
            Base.metadata.create_all(self.engine)
            return
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
        )
        config.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))
        command.upgrade(config, "head")

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._sessions() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def close(self) -> None:
        self.engine.dispose()


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def seed(self, camera_name: str, capability_id: str) -> None:
        with self.database.session() as session:
            if session.get(ConfigState, 1) is None:
                session.add(ConfigState(id=1, active_capability_id=capability_id))
            if session.get(CameraRecord, camera_name) is None:
                session.add(
                    CameraRecord(
                        id=camera_name,
                        name=camera_name,
                        stream_secret_ref="env:CAMZILLA_CAMERA_RTSP_URL",
                        allowed_categories=["person"],
                    )
                )
            if session.get(AlertRuleRecord, "person-detected") is None:
                session.add(
                    AlertRuleRecord(
                        id="person-detected",
                        camera_id=camera_name,
                        target_categories=["person"],
                    )
                )

    def active_capability_id(self) -> str:
        with self.database.session() as session:
            state = session.get(ConfigState, 1)
            if state is None:
                raise RuntimeError("configuration is not initialized")
            return state.active_capability_id

    def set_active_capability(self, capability_id: str) -> None:
        with self.database.session() as session:
            state = session.get(ConfigState, 1)
            if state is None:
                raise RuntimeError("configuration is not initialized")
            state.active_capability_id = capability_id
            state.version += 1

    def configuration_version(self) -> int:
        with self.database.session() as session:
            state = session.get(ConfigState, 1)
            if state is None:
                raise RuntimeError("configuration is not initialized")
            return state.version

    def update_rule(
        self,
        rule_id: str,
        *,
        expected_config_version: int,
        confidence_threshold: float,
        debounce_seconds: float,
        schedule_start: str | None,
        schedule_end: str | None,
        zone: list[list[float]] | None,
        target_categories: list[str],
    ) -> int:
        with self.database.session() as session:
            state = session.get(ConfigState, 1)
            rule = session.get(AlertRuleRecord, rule_id)
            if state is None or rule is None:
                raise KeyError(rule_id)
            if state.version != expected_config_version:
                raise ConfigurationConflictError("configuration version conflict")
            rule.confidence_threshold = confidence_threshold
            rule.debounce_seconds = debounce_seconds
            rule.schedule_start = schedule_start
            rule.schedule_end = schedule_end
            rule.zone = zone
            rule.target_categories = target_categories
            rule.version += 1
            state.version += 1
            return state.version

    def record_event(
        self,
        *,
        event_id: str,
        camera_id: str,
        rule_id: str | None,
        event_type: str,
        triggered_at: datetime,
        categories: list[str],
        snapshot_path: str | None = None,
        clip_path: str | None = None,
    ) -> None:
        if triggered_at.tzinfo is None:
            triggered_at = triggered_at.replace(tzinfo=UTC)
        with self.database.session() as session:
            session.add(
                EventRecord(
                    id=event_id,
                    camera_id=camera_id,
                    rule_id=rule_id,
                    event_type=event_type,
                    triggered_at=triggered_at,
                    categories=categories,
                    snapshot_path=snapshot_path,
                    clip_path=clip_path,
                )
            )
