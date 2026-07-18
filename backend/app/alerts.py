"""Bounded in-memory alert evaluation and notifier adapters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Literal, Protocol, cast

import httpx

from .config import Settings
from .contracts import (
    AlertAttachment,
    AlertEvent,
    AlertPayload,
    AlertRule,
    AlertRuntimeStatus,
    DetectionMessage,
)
from .inference import Frame


class Notifier(Protocol):
    @property
    def mode(self) -> Literal["dry-run", "discord"]: ...

    async def send(self, payload: AlertPayload) -> None: ...


class NotifierDeliveryError(Exception):
    """A redacted notifier failure safe to expose through status APIs."""


class SnapshotError(Exception):
    pass


class DryRunNotifier:
    mode: Literal["dry-run"] = "dry-run"

    def __init__(self) -> None:
        self.evaluated_events = 0

    async def send(self, payload: AlertPayload) -> None:
        del payload
        self.evaluated_events += 1


def valid_discord_webhook_url(value: str) -> bool:
    try:
        url = httpx.URL(value)
    except Exception:
        return False
    return (
        url.scheme == "https"
        and url.host in {"discord.com", "discordapp.com"}
        and url.path.startswith("/api/webhooks/")
        and len(url.path.split("/")) >= 5
    )


class DiscordNotifier:
    mode: Literal["discord"] = "discord"

    def __init__(
        self,
        webhook_url: str,
        *,
        attempts: int = 3,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        sleep: Callable[[float], Coroutine[Any, Any, None]] = asyncio.sleep,
    ) -> None:
        if not valid_discord_webhook_url(webhook_url):
            raise ValueError("Discord webhook URL is invalid")
        self._webhook_url = webhook_url
        self.attempts = attempts
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=10))
        self._sleep = sleep

    async def send(self, payload: AlertPayload) -> None:
        files: list[tuple[str, tuple[str | None, bytes | str, str]]] = [
            (
                "payload_json",
                (None, json.dumps({"content": payload.text}), "application/json"),
            )
        ]
        files.extend(
            (
                f"files[{index}]",
                (attachment.filename, attachment.data, attachment.mime_type),
            )
            for index, attachment in enumerate(payload.attachments)
        )
        for attempt in range(self.attempts):
            try:
                async with self._client_factory() as client:
                    response = await client.post(self._webhook_url, files=files)
            except httpx.RequestError:
                response = None
            if response is not None and response.status_code < 400:
                return
            retryable = (
                response is None or response.status_code == 429 or response.status_code >= 500
            )
            if not retryable or attempt + 1 == self.attempts:
                raise NotifierDeliveryError("Discord delivery failed")
            delay = min(2**attempt, 5.0)
            if response is not None and response.status_code == 429:
                delay = self._retry_after(response, delay)
            await self._sleep(delay)

    @staticmethod
    def _retry_after(response: httpx.Response, fallback: float) -> float:
        try:
            value = float(response.json().get("retry_after", fallback))
        except (TypeError, ValueError, json.JSONDecodeError):
            value = fallback
        return min(max(value, 0.05), 5.0)


class SnapshotRenderer:
    def __init__(self, max_bytes: int = 8 * 1024 * 1024, max_dimension: int = 1600) -> None:
        self.max_bytes = max_bytes
        self.max_dimension = max_dimension

    async def render(
        self, frame: Frame, message: DetectionMessage, target_classes: frozenset[str]
    ) -> AlertAttachment | None:
        if frame.image is None:
            return None
        return await asyncio.to_thread(self._render_sync, frame, message, target_classes)

    def _render_sync(
        self, frame: Frame, message: DetectionMessage, target_classes: frozenset[str]
    ) -> AlertAttachment:
        try:
            import cv2
        except ImportError as error:
            raise SnapshotError("snapshot encoder is unavailable") from error
        source_image = frame.image
        if source_image is None:
            raise SnapshotError("snapshot frame is unavailable")
        image = source_image.copy()
        height, width = image.shape[:2]
        scale = min(1.0, self.max_dimension / max(width, height))
        if scale < 1:
            image = cv2.resize(image, (round(width * scale), round(height * scale)))
            height, width = image.shape[:2]
        for detection in message.detections:
            if detection.class_name not in target_classes:
                continue
            box = detection.box
            start = (round(box.x * width), round(box.y * height))
            end = (round((box.x + box.width) * width), round((box.y + box.height) * height))
            cv2.rectangle(image, start, end, (0, 220, 70), 3)
            cv2.putText(
                image,
                f"{detection.class_name} {detection.confidence:.0%}",
                (start[0], max(20, start[1] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
            )
        encoded: bytes | None = None
        for quality in (85, 70, 55):
            ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if ok and len(data) <= self.max_bytes:
                encoded = data.tobytes()
                break
        if encoded is None:
            raise SnapshotError("snapshot exceeds attachment limit")
        return AlertAttachment(filename="alert.jpg", mime_type="image/jpeg", data=encoded)


@dataclass(frozen=True)
class AlertCandidate:
    frame: Frame
    message: DetectionMessage
    event: AlertEvent


class AlertEngine:
    """Evaluate synchronously and deliver through one bounded background worker."""

    def __init__(
        self,
        rule: AlertRule,
        notifier: Notifier,
        *,
        requested_notifier: Literal["dry-run", "discord"],
        external_delivery_configured: bool,
        configuration_reason: str | None,
        renderer: SnapshotRenderer | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.rule = rule
        self.notifier = notifier
        self.requested_notifier = requested_notifier
        self.external_delivery_configured = external_delivery_configured
        self.configuration_reason = configuration_reason
        self.renderer = renderer or SnapshotRenderer()
        self.clock = clock
        self.queue: asyncio.Queue[AlertCandidate] = asyncio.Queue(maxsize=1)
        self._delivery_task: asyncio.Task[None] | None = None
        self._last_trigger_at: float | None = None
        self.delivered_events = 0
        self.dry_run_events = 0
        self.failed_events = 0
        self.dropped_events = 0
        self.suppressed_events = 0
        self.last_event_at: datetime | None = None
        self.last_error: str | None = None

    async def start(self) -> None:
        self._delivery_task = asyncio.create_task(self._deliver())

    def observe(self, frame: Frame, message: DetectionMessage) -> None:
        if not self.rule.enabled or message.detections == []:
            return
        matched = [
            item
            for item in message.detections
            if item.class_name in self.rule.target_classes
            and item.confidence >= self.rule.confidence_threshold
        ]
        if not matched:
            return
        now = self.clock()
        if (
            self._last_trigger_at is not None
            and now - self._last_trigger_at < self.rule.debounce_seconds
        ):
            self.suppressed_events += 1
            return
        self._last_trigger_at = now
        source_image = frame.image
        copied_image = (
            source_image.copy()
            if source_image is not None and hasattr(source_image, "copy")
            else source_image
        )
        candidate = AlertCandidate(
            Frame(frame.width, frame.height, frame.capture_timestamp, copied_image),
            message,
            AlertEvent(
                rule_id=self.rule.id,
                camera_name=self.rule.camera_name,
                triggered_at=datetime.now(UTC),
                detection_sequence=message.sequence,
                matched_classes=frozenset(item.class_name for item in matched),
            ),
        )
        try:
            self.queue.put_nowait(candidate)
        except asyncio.QueueFull:
            self.dropped_events += 1

    async def _deliver(self) -> None:
        while True:
            candidate = await self.queue.get()
            try:
                attachment = await self.renderer.render(
                    candidate.frame, candidate.message, self.rule.target_classes
                )
                classes = ", ".join(sorted(candidate.event.matched_classes))
                payload = AlertPayload(
                    event=candidate.event,
                    text=f"Camzilla detected {classes} at {self.rule.camera_name}",
                    attachments=[attachment] if attachment else [],
                )
                await self.notifier.send(payload)
                self.delivered_events += 1
                if self.notifier.mode == "dry-run":
                    self.dry_run_events += 1
                self.last_event_at = candidate.event.triggered_at
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception:
                self.failed_events += 1
                self.last_error = "alert delivery failed"
            finally:
                self.queue.task_done()

    def status(self) -> AlertRuntimeStatus:
        return AlertRuntimeStatus(
            rule=self.rule,
            requested_notifier=self.requested_notifier,
            effective_notifier=self.notifier.mode,
            external_delivery_configured=self.external_delivery_configured,
            configuration_reason=self.configuration_reason,
            queued_events=self.queue.qsize(),
            delivered_events=self.delivered_events,
            dry_run_events=self.dry_run_events,
            failed_events=self.failed_events,
            dropped_events=self.dropped_events,
            suppressed_events=self.suppressed_events,
            last_event_at=self.last_event_at,
            last_error=self.last_error,
        )

    async def close(self) -> None:
        if self._delivery_task:
            self._delivery_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._delivery_task


def build_alert_engine(settings: Settings) -> AlertEngine:
    rule = AlertRule(
        id="person-detected",
        camera_name=settings.camera_name,
        target_classes=settings.alert_class_filter or frozenset({"person"}),
        confidence_threshold=settings.alert_confidence_threshold,
        debounce_seconds=settings.alert_debounce_seconds,
        enabled=settings.alerts_enabled,
    )
    requested = cast(Literal["dry-run", "discord"], settings.notifier)
    webhook = (
        settings.discord_webhook_url.get_secret_value()
        if settings.discord_webhook_url is not None
        else ""
    )
    configured = (
        requested == "discord"
        and settings.discord_delivery_confirmed
        and valid_discord_webhook_url(webhook)
    )
    if configured:
        notifier: Notifier = DiscordNotifier(webhook)
        reason = None
    else:
        notifier = DryRunNotifier()
        if requested == "discord":
            reason = "Discord delivery requires a valid webhook and explicit confirmation"
        else:
            reason = "Dry-run mode does not send external notifications"
    return AlertEngine(
        rule,
        notifier,
        requested_notifier=requested,
        external_delivery_configured=configured,
        configuration_reason=reason,
    )
