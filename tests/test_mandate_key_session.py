"""A mandate-key session: no refresh token, renewed by logging in again.

Runs against a real local token endpoint: the session's first login asks for a
mesh key, every renewal logs in again without one, and a revoked key surfaces as
"needs a new key" instead of looping.
"""

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from aiohttp import web
from pydantic import SecretStr

from fakts import Fakts
from fakts.errors import NeedsReauthenticationError
from fakts.grants.remote import RemoteGrant
from fakts.grants.remote.authorizers.mandate_key import MandateKeyAuthorizer
from fakts.grants.remote.discovery.static import StaticDiscovery
from fakts.grants.remote.models import FaktsEndpoint

from .helpers import MemoryCache, make_manifest

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def token_endpoint() -> AsyncIterator[Callable[[Handler], Awaitable[str]]]:
    runners: list[web.AppRunner] = []

    async def start(handler: Handler) -> str:
        app = web.Application()
        app.router.add_post("/o/token/", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        return f"http://127.0.0.1:{runner.addresses[0][1]}/"

    yield start
    for runner in runners:
        await runner.cleanup()


def _body(n: int) -> dict:
    return {
        "access_token": f"access-{n}",
        "expires_in": 3600,
        "token_type": "Bearer",
        "client_id": "keyed-client",
        "self": {
            "deployment_name": "test",
            "alias": {"id": "self", "host": "localhost", "port": 8000, "path": "lok"},
        },
        "instances": {},
    }


def _fakts(base_url: str) -> Fakts:
    endpoint = FaktsEndpoint(
        base_url=base_url,
        name="Test",
        protocol_version="2",
        issuer=base_url,
        token_endpoint=f"{base_url}o/token/",
    )
    return Fakts(
        grant=RemoteGrant(
            discovery=StaticDiscovery(endpoint=endpoint),
            authorizer=MandateKeyAuthorizer(
                manifest=make_manifest(),
                key=SecretStr("k" * 40),
                request_auth_key=True,
                allow_insecure_transport=True,
            ),
        ),
        cache=MemoryCache(),
        manifest=make_manifest(),
        allow_insecure_transport=True,
    )


async def test_a_key_session_renews_by_logging_in_again(token_endpoint) -> None:
    logins: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        form = await request.post()
        assert form["grant_type"] == "urn:fakts:grant-type:mandate-key"
        logins.append(str(form["request_auth_key"]))
        return web.json_response(_body(len(logins)))

    fakts = _fakts(await token_endpoint(handler))
    async with fakts:
        first = await fakts.aget_token()
        # What a transport does when the service rejects the token (or it ran out).
        second = await fakts.arefresh_token(first)
        loaded = await fakts.aload()

    assert (first, second) == ("access-1", "access-2")
    # Only the first login asks for a mesh key.
    assert logins == ["true", "false"]
    assert loaded.auth.refresh_token is None
    assert loaded.auth.client_id == "keyed-client"


async def test_a_revoked_key_needs_a_new_one(token_endpoint) -> None:
    calls = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return web.json_response(_body(1))
        return web.json_response(
            {
                "error": "invalid_grant",
                "error_description": "This mandate has been revoked or has expired.",
            },
            status=400,
        )

    fakts = _fakts(await token_endpoint(handler))
    async with fakts:
        first = await fakts.aget_token()
        with pytest.raises(NeedsReauthenticationError, match="mandate key"):
            await fakts.arefresh_token(first)

    assert calls["n"] == 2
