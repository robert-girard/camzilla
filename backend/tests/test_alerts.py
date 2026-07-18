import asyncio
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.alerts import (
    AlertEngine,
    DiscordNotifier,
    DryRunNotifier,
    NotifierDeliveryError,
    SnapshotError,
    SnapshotRenderer,
    build_alert_engine,
)
from app.config import Settings
from app.contracts import (
    AlertAttachment,
    AlertEvent,
    AlertPayload,
    AlertRule,
    Detection,
    DetectionMessage,
    NormalizedBox,
)
from app.inference import Frame


def detection_message(sequence: int = 1, confidence: float = 0.91) -> DetectionMessage:
    now = datetime.now(UTC)
    return DetectionMessage(
        sequence=sequence,
        capture_timestamp=now,
        result_timestamp=now,
        source_width=640,
        source_height=480,
        backend_id="fake",
        model_id="fake-person-v1",
        target="cpu",
        device="synthetic",
        inference_ms=1,
        inference_fps=5,
        detections=[
            Detection(
                class_name="person",
                semantic_id="coco:person",
                native_class_id=0,
                confidence=confidence,
                box=NormalizedBox(x=0.2, y=0.2, width=0.3, height=0.5),
            )
        ],
    )


class RecordingRenderer:
    async def render(self, frame, message, target_classes):
        del frame, message, target_classes
        return AlertAttachment(filename="alert.jpg", mime_type="image/jpeg", data=b"jpeg")


class RecordingNotifier:
    mode = "discord"

    def __init__(self) -> None:
        self.payloads = []

    async def send(self, payload) -> None:
        self.payloads.append(payload)


def alert_engine(notifier, clock) -> AlertEngine:
    return AlertEngine(
        AlertRule(
            id="person-detected",
            camera_name="front-door",
            confidence_threshold=0.7,
            debounce_seconds=5,
        ),
        notifier,
        requested_notifier=notifier.mode,
        external_delivery_configured=notifier.mode == "discord",
        configuration_reason=None,
        renderer=RecordingRenderer(),
        clock=clock,
    )


@pytest.mark.asyncio
async def test_alert_engine_debounces_at_the_exact_boundary() -> None:
    times = iter((0.0, 4.99, 5.0))
    notifier = RecordingNotifier()
    engine = alert_engine(notifier, lambda: next(times))
    await engine.start()
    frame = Frame(640, 480, datetime.now(UTC))

    engine.observe(frame, detection_message(1))
    await engine.queue.join()
    engine.observe(frame, detection_message(2))
    engine.observe(frame, detection_message(3))
    await engine.queue.join()
    await engine.close()

    assert len(notifier.payloads) == 2
    assert engine.suppressed_events == 1
    assert notifier.payloads[0].attachments[0].data == b"jpeg"
    assert notifier.payloads[1].event.detection_sequence == 3


@pytest.mark.asyncio
async def test_notifier_failure_is_isolated_and_redacted() -> None:
    class BrokenNotifier:
        mode = "discord"

        async def send(self, _payload):
            raise RuntimeError("private webhook and payload")

    engine = alert_engine(BrokenNotifier(), lambda: 0.0)
    await engine.start()
    engine.observe(Frame(640, 480, datetime.now(UTC)), detection_message())
    await engine.queue.join()
    status = engine.status()
    await engine.close()

    assert status.failed_events == 1
    assert status.last_error == "alert delivery failed"
    assert "private" not in status.model_dump_json()


@pytest.mark.asyncio
async def test_stream_down_policy_suppresses_repeats_and_reports_recovery() -> None:
    times = iter((0.0, 10.0))
    notifier = RecordingNotifier()
    engine = AlertEngine(
        AlertRule(id="person-detected", camera_name="front-door"),
        notifier,
        requested_notifier="discord",
        external_delivery_configured=True,
        configuration_reason=None,
        renderer=RecordingRenderer(),
        clock=lambda: next(times),
        stream_down_repeat_seconds=60,
    )
    await engine.start()

    engine.observe_stream_state("degraded")
    await engine.queue.join()
    engine.observe_stream_state("connecting")
    engine.observe_stream_state("degraded")
    await engine.queue.join()
    engine.observe_stream_state("ready")
    await engine.queue.join()
    status = engine.status()
    await engine.close()

    assert [item.text for item in notifier.payloads] == [
        "Camzilla stream is unavailable at front-door",
        "Camzilla stream recovered at front-door",
    ]
    assert status.stream_down_events == 1
    assert status.stream_recovery_events == 1
    assert status.suppressed_events == 1
    assert status.stream_state == "ready"


def test_alert_rule_applies_overnight_schedule_and_normalized_zone() -> None:
    frame = Frame(640, 480, datetime.now(UTC))
    outside_zone = AlertEngine(
        AlertRule(
            id="person-detected",
            camera_name="front-door",
            schedule_start="22:00",
            schedule_end="06:00",
            zone=[(0.7, 0.1), (0.95, 0.1), (0.95, 0.9), (0.7, 0.9)],
        ),
        DryRunNotifier(),
        requested_notifier="dry-run",
        external_delivery_configured=False,
        configuration_reason=None,
        wall_clock=lambda: datetime(2026, 7, 17, 23, 0, tzinfo=UTC),
    )
    outside_zone.observe(frame, detection_message())
    assert outside_zone.queue.qsize() == 0

    inactive_schedule = AlertEngine(
        AlertRule(
            id="person-detected",
            camera_name="front-door",
            schedule_start="22:00",
            schedule_end="06:00",
        ),
        DryRunNotifier(),
        requested_notifier="dry-run",
        external_delivery_configured=False,
        configuration_reason=None,
        wall_clock=lambda: datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
    )
    inactive_schedule.observe(frame, detection_message())
    assert inactive_schedule.queue.qsize() == 0

    active = AlertEngine(
        AlertRule(
            id="person-detected",
            camera_name="front-door",
            schedule_start="22:00",
            schedule_end="06:00",
        ),
        DryRunNotifier(),
        requested_notifier="dry-run",
        external_delivery_configured=False,
        configuration_reason=None,
        wall_clock=lambda: datetime(2026, 7, 17, 23, 0, tzinfo=UTC),
    )
    active.observe(frame, detection_message())
    assert active.queue.qsize() == 1


def test_attachment_contract_rejects_payloads_over_discord_limit() -> None:
    with pytest.raises(ValidationError):
        AlertAttachment(
            filename="too-large.jpg",
            mime_type="image/jpeg",
            data=b"x" * (8 * 1024 * 1024 + 1),
        )


@pytest.mark.asyncio
async def test_snapshot_renderer_annotates_a_copy_and_enforces_limit(monkeypatch) -> None:
    rectangles = []

    class Image:
        shape = (480, 640, 3)

        def __init__(self, copied=False):
            self.copied = copied

        def copy(self):
            return Image(copied=True)

    class Encoded:
        def __init__(self, size):
            self.size = size

        def __len__(self):
            return self.size

        def tobytes(self):
            return b"jpeg"

    fake_cv2 = SimpleNamespace(
        IMWRITE_JPEG_QUALITY=1,
        FONT_HERSHEY_SIMPLEX=2,
        resize=lambda image, _dimensions: image,
        rectangle=lambda image, start, end, _color, _width: rectangles.append(
            (image.copied, start, end)
        ),
        putText=lambda *_args: None,
        imencode=lambda _extension, _image, _options: (True, Encoded(4)),
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    renderer = SnapshotRenderer(max_bytes=4)
    attachment = await renderer.render(
        Frame(640, 480, datetime.now(UTC), Image()),
        detection_message(),
        frozenset({"coco:person"}),
    )

    assert attachment is not None and attachment.data == b"jpeg"
    assert rectangles == [(True, (128, 96), (320, 336))]

    fake_cv2.imencode = lambda _extension, _image, _options: (True, Encoded(5))
    with pytest.raises(SnapshotError):
        await SnapshotRenderer(max_bytes=4).render(
            Frame(640, 480, datetime.now(UTC), Image()),
            detection_message(),
            frozenset({"coco:person"}),
        )


def payload() -> AlertPayload:
    return AlertPayload(
        event=AlertEvent(
            rule_id="person-detected",
            camera_name="front-door",
            triggered_at=datetime.now(UTC),
            detection_sequence=1,
            matched_classes=frozenset({"coco:person"}),
        ),
        text="Camzilla detected person",
        attachments=[AlertAttachment(filename="alert.jpg", mime_type="image/jpeg", data=b"x")],
    )


@pytest.mark.asyncio
async def test_discord_notifier_honors_rate_limit_then_retries() -> None:
    responses = [
        httpx.Response(429, json={"retry_after": 0.25}),
        httpx.Response(204),
    ]
    calls = []
    sleeps = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, files):
            calls.append((url, files))
            return responses.pop(0)

    async def record_sleep(delay):
        sleeps.append(delay)

    notifier = DiscordNotifier(
        "https://discord.com/api/webhooks/example/token",
        client_factory=Client,
        sleep=record_sleep,
    )
    await notifier.send(payload())

    assert len(calls) == 2
    assert sleeps == [0.25]
    assert calls[0][1][0][0] == "payload_json"
    assert calls[0][1][1][0] == "files[0]"


@pytest.mark.asyncio
async def test_discord_notifier_redacts_webhook_after_retry_exhaustion() -> None:
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, files):
            del files
            return httpx.Response(503)

    async def no_sleep(_delay):
        await asyncio.sleep(0)

    webhook = "https://discord.com/api/webhooks/private/secret-token"
    notifier = DiscordNotifier(webhook, client_factory=Client, sleep=no_sleep)
    with pytest.raises(NotifierDeliveryError) as caught:
        await notifier.send(payload())
    assert webhook not in str(caught.value)
    assert "secret-token" not in str(caught.value)


def test_discord_delivery_requires_url_and_explicit_confirmation() -> None:
    unconfirmed = build_alert_engine(
        Settings(
            _env_file=None,
            notifier="discord",
            discord_webhook_url="https://discord.com/api/webhooks/example/token",
        )
    )
    confirmed = build_alert_engine(
        Settings(
            _env_file=None,
            notifier="discord",
            discord_webhook_url="https://discord.com/api/webhooks/example/token",
            discord_delivery_confirmed=True,
        )
    )

    assert isinstance(unconfirmed.notifier, DryRunNotifier)
    assert unconfirmed.external_delivery_configured is False
    assert isinstance(confirmed.notifier, DiscordNotifier)
    assert confirmed.external_delivery_configured is True
