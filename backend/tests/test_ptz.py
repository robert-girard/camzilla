import pytest

from app.contracts import PtzCapabilityResponse, PtzMoveRequest
from app.ptz import (
    OnvifPtzConfig,
    OnvifPtzController,
    PtzBusyError,
    PtzService,
    direction_velocity,
)


class RecordingController:
    def __init__(self) -> None:
        self.requests: list[PtzMoveRequest] = []

    async def continuous_move(self, request: PtzMoveRequest) -> None:
        self.requests.append(request)


def available_capability() -> PtzCapabilityResponse:
    return PtzCapabilityResponse(
        camera_name="front-door",
        available=True,
        verified=True,
        supports_continuous_move=True,
    )


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("left", (-0.2, 0.0, 0.0)),
        ("right", (0.2, 0.0, 0.0)),
        ("up", (0.0, 0.2, 0.0)),
        ("down", (0.0, -0.2, 0.0)),
        ("in", (0.0, 0.0, 0.2)),
        ("out", (0.0, 0.0, -0.2)),
    ],
)
def test_direction_mapping(direction, expected) -> None:
    assert direction_velocity(direction, 0.2) == expected


@pytest.mark.asyncio
async def test_ptz_service_enforces_server_side_throttle() -> None:
    controller = RecordingController()
    times = iter((1.0, 1.1, 1.5))
    service = PtzService(
        available_capability(), controller, minimum_interval_seconds=0.25, clock=lambda: next(times)
    )
    request = PtzMoveRequest(direction="left", speed=0.2, duration_seconds=0.5)

    await service.move(request)
    with pytest.raises(PtzBusyError):
        await service.move(request)
    await service.move(request)

    assert controller.requests == [request, request]


@pytest.mark.asyncio
async def test_onvif_adapter_sends_only_a_timed_continuous_move() -> None:
    calls = []

    class Response:
        status_code = 200

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, content, headers):
            calls.append((url, content.decode(), headers))
            return Response()

    controller = OnvifPtzController(
        OnvifPtzConfig(
            endpoint="http://camera.local:8000/onvif/PTZ",
            username="operator",
            password="placeholder-password",
            profile="PROFILE_000",
        ),
        client_factory=Client,
    )

    await controller.continuous_move(
        PtzMoveRequest(direction="right", speed=0.2, duration_seconds=1)
    )

    assert calls[0][0] == "http://camera.local:8000/onvif/PTZ"
    assert "<tptz:ContinuousMove>" in calls[0][1]
    assert '<tt:PanTilt x="0.2" y="0"/>' in calls[0][1]
    assert "<tptz:Timeout>PT1S</tptz:Timeout>" in calls[0][1]
    assert "Stop" not in calls[0][1]
