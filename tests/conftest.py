"""Fixtures shared by the unit tests. The docker stacks have their own conftest
(tests/integration, tests/mesh_lab); nothing here needs docker."""

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from aiohttp import web

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@pytest.fixture(autouse=True)
def no_refresh_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refresh retry backs off for real (0.25 s, jittered); tests don't wait."""
    monkeypatch.setattr("fakts.session.REFRESH_RETRY_DELAY", 0)


@pytest_asyncio.fixture
async def token_server() -> AsyncIterator[Callable[..., Awaitable[str]]]:
    """Start token endpoints on 127.0.0.1; each call serves one handler at /token."""
    runners = []

    async def start(handler: Handler) -> str:
        app = web.Application()
        app.router.add_route("POST", "/token", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        return f"http://127.0.0.1:{runner.addresses[0][1]}/token"

    yield start

    for runner in runners:
        await runner.cleanup()
