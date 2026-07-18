import asyncio
from datetime import UTC, datetime

import pytest

from app.inference import Frame
from app.scheduling import FairFrameScheduler


def frame(width: int) -> Frame:
    return Frame(width, 480, datetime.now(UTC))


@pytest.mark.asyncio
async def test_scheduler_keeps_latest_per_camera_without_starvation() -> None:
    scheduler = FairFrameScheduler()
    await scheduler.submit("busy", frame(1))
    await scheduler.submit("busy", frame(2))
    await scheduler.submit("quiet", frame(3))
    await scheduler.submit("busy", frame(4))

    first = await scheduler.next()
    second = await scheduler.next()

    assert (first.camera_id, first.frame.width) == ("busy", 4)
    assert (second.camera_id, second.frame.width) == ("quiet", 3)
    assert scheduler.dropped == {"busy": 2}
    assert scheduler.pending_cameras == 0


@pytest.mark.asyncio
async def test_scheduler_waits_for_and_bounds_each_new_camera() -> None:
    scheduler = FairFrameScheduler()
    waiting = asyncio.create_task(scheduler.next())
    await asyncio.sleep(0)
    await scheduler.submit("side-door", frame(5))
    result = await waiting
    assert result.camera_id == "side-door"

    for index in range(100):
        await scheduler.submit("front-door", frame(index + 1))
        await scheduler.submit("side-door", frame(index + 1))
    assert scheduler.pending_cameras == 2
    assert scheduler.dropped == {"front-door": 99, "side-door": 99}
