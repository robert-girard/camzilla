import pytest

from app.queueing import LatestItemQueue


@pytest.mark.asyncio
async def test_latest_item_queue_replaces_unprocessed_item() -> None:
    queue = LatestItemQueue[int]()
    queue.put_latest(1)
    queue.put_latest(2)
    assert await queue.get() == 2
    queue.done()
    assert queue.dropped == 1
