import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class LatestItemQueue(Generic[T]):
    """A size-one queue whose producer replaces stale, unprocessed work."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=1)
        self.dropped = 0

    def put_latest(self, item: T) -> None:
        if self._queue.full():
            self._queue.get_nowait()
            self._queue.task_done()
            self.dropped += 1
        self._queue.put_nowait(item)

    async def get(self) -> T:
        return await self._queue.get()

    def done(self) -> None:
        self._queue.task_done()


async def consume_latest(
    queue: LatestItemQueue[T], handler: Callable[[T], Awaitable[object]]
) -> None:
    while True:
        item = await queue.get()
        try:
            await handler(item)
        finally:
            queue.done()
