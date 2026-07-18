"""SQLAlchemy persistence boundary for local single-node configuration and events."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .contracts import (
    AlertRuleConfiguration,
    CameraConfiguration,
    EventPage,
    EventSummary,
    GlobalConfiguration,
    NormalizedPoint,
    PolygonZone,
)


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

    def set_camera_capabilities(self, camera_id: str, capabilities: dict[str, Any]) -> None:
        with self.database.session() as session:
            camera = session.get(CameraRecord, camera_id)
            if camera is None:
                raise KeyError(camera_id)
            if camera.capabilities != capabilities:
                camera.capabilities = capabilities
                camera.version += 1

    def configuration_version(self) -> int:
        with self.database.session() as session:
            state = session.get(ConfigState, 1)
            if state is None:
                raise RuntimeError("configuration is not initialized")
            return state.version

    def configuration(self) -> GlobalConfiguration:
        with self.database.session() as session:
            state = session.get(ConfigState, 1)
            if state is None:
                raise RuntimeError("configuration is not initialized")
            cameras = list(session.scalars(select(CameraRecord).order_by(CameraRecord.name)))
            rules = list(session.scalars(select(AlertRuleRecord).order_by(AlertRuleRecord.id)))
            return GlobalConfiguration(
                version=state.version,
                active_capability_id=state.active_capability_id,
                cameras=[
                    CameraConfiguration(
                        id=item.id,
                        name=item.name,
                        enabled=item.enabled,
                        capabilities=item.capabilities,
                        allowed_categories=item.allowed_categories,
                        catalog_revision=item.catalog_revision,
                        version=item.version,
                    )
                    for item in cameras
                ],
                alert_rules=[
                    AlertRuleConfiguration(
                        id=item.id,
                        camera_id=item.camera_id,
                        enabled=item.enabled,
                        target_categories=item.target_categories,
                        confidence_threshold=item.confidence_threshold,
                        debounce_seconds=item.debounce_seconds,
                        schedule_start=item.schedule_start,
                        schedule_end=item.schedule_end,
                        zone=(
                            PolygonZone(
                                points=[
                                    NormalizedPoint(x=point[0], y=point[1]) for point in item.zone
                                ]
                            )
                            if item.zone
                            else None
                        ),
                        version=item.version,
                    )
                    for item in rules
                ],
            )

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

    def list_events(
        self,
        *,
        page: int,
        page_size: int,
        camera_id: str | None = None,
        event_type: str | None = None,
        category: str | None = None,
        descending: bool = True,
    ) -> EventPage:
        with self.database.session() as session:
            statement = select(EventRecord)
            if camera_id:
                statement = statement.where(EventRecord.camera_id == camera_id)
            if event_type:
                statement = statement.where(EventRecord.event_type == event_type)
            if category:
                statement = statement.where(EventRecord.categories.contains(category))
            total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            order = (
                EventRecord.triggered_at.desc() if descending else EventRecord.triggered_at.asc()
            )
            records = list(
                session.scalars(
                    statement.order_by(order).offset((page - 1) * page_size).limit(page_size)
                )
            )
            return EventPage(
                items=[
                    EventSummary(
                        id=UUID(record.id),
                        camera_id=record.camera_id,
                        rule_id=record.rule_id,
                        event_type=record.event_type,
                        triggered_at=record.triggered_at,
                        categories=record.categories,
                        has_snapshot=record.snapshot_path is not None,
                        has_clip=record.clip_path is not None,
                    )
                    for record in records
                ],
                page=page,
                page_size=page_size,
                total=total,
                pages=(total + page_size - 1) // page_size,
            )

    def delete_event(self, event_id: str) -> tuple[str | None, str | None] | None:
        with self.database.session() as session:
            event = session.get(EventRecord, event_id)
            if event is None:
                return None
            paths = (event.snapshot_path, event.clip_path)
            session.execute(delete(EventRecord).where(EventRecord.id == event_id))
            return paths
