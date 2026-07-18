import pytest

from app.pipeline import OpenCvRestreamSource


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeImage:
    shape = (360, 640, 3)


class FakeCapture:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.grabbed = 0
        self.retrieved: list[int] = []
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 - mirrors OpenCV's API
        return True

    def grab(self) -> bool:
        self.grabbed += 1
        self.clock.now += 0.04
        return True

    def retrieve(self) -> tuple[bool, FakeImage]:
        self.retrieved.append(self.grabbed)
        return True, FakeImage()

    def release(self) -> None:
        self.released = True


@pytest.mark.asyncio
async def test_restream_source_reports_unavailable_without_exposing_url() -> None:
    source = OpenCvRestreamSource("rtsp://go2rtc:8554/front-door", 5)
    with pytest.raises(RuntimeError, match="restream"):
        await anext(source.frames())


@pytest.mark.asyncio
async def test_restream_source_drains_frames_between_samples() -> None:
    clock = FakeClock()
    capture = FakeCapture(clock)
    source = OpenCvRestreamSource(
        "rtsp://go2rtc:8554/front-door",
        fps=5,
        capture_factory=lambda _: capture,
        clock=clock,
    )
    frames = source.frames()

    first = await anext(frames)
    second = await anext(frames)
    await frames.aclose()

    assert (first.width, first.height) == (640, 360)
    assert (second.width, second.height) == (640, 360)
    assert capture.retrieved[0] == 1
    assert capture.retrieved[1] >= 5
    assert source.dropped_frames == capture.retrieved[1] - 2
    assert capture.released
