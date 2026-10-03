"""Cancel generation when the HTTP caller disconnects."""
import asyncio
from contextlib import suppress

from fastapi import Request


async def run_connected(request: Request, operation):
    async def watch():
        # is_disconnected() uses a cancelling AnyIO scope that can swallow task
        # cancellation. The parsed body has already been consumed by FastAPI.
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                return

    work = asyncio.create_task(operation)
    watcher = asyncio.create_task(watch())
    try:
        done, _ = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            raise asyncio.CancelledError()
        return await work
    finally:
        for task in (work, watcher):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task
