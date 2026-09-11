"""Unit tests for the remote grant subsystem (claimer, redeem demander and
discovery utils), exercised against a real local ``aiohttp.web`` server.

This mirrors the local-server pattern used by ``test_challenge.py`` rather
than mocking aiohttp, so the actual request/response handling is covered.
"""

from typing import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from aiohttp import web

from fakts_next.grants.remote.claimers.post import ClaimEndpointClaimer
from fakts_next.grants.remote.demanders.redeem import RedeemDemander
from fakts_next.grants.remote.demanders.retrieve import RetrieveError
from fakts_next.grants.remote.discovery.utils import check_wellknown, discover_url
from fakts_next.grants.remote.errors import ClaimError, DiscoveryError
from fakts_next.grants.remote.models import FaktsEndpoint
from fakts_next.models import ActiveFakts

from .test_fakts_behavior import make_fakts_value, make_manifest

pytestmark = pytest.mark.asyncio


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@pytest_asyncio.fixture
async def local_server() -> AsyncIterator[Callable[..., Awaitable[str]]]:
    """Starts a local http server and returns a callable that registers
    a handler for a path and yields the server's base_url (with trailing
    slash, as the remote components expect)."""
    runners = []

    async def start(routes: dict[str, Handler], method: str = "POST") -> str:
        app = web.Application()
        for path, handler in routes.items():
            app.router.add_route(method, path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        port = runner.addresses[0][1]
        return f"http://127.0.0.1:{port}/"

    yield start

    for runner in runners:
        await runner.cleanup()


# --------------------------------------------------------------------------- #
# ClaimEndpointClaimer
# --------------------------------------------------------------------------- #


async def test_claim_granted_returns_active_fakts(local_server) -> None:
    config = make_fakts_value().model_dump()

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        assert body["token"] == "tok"
        assert body["secure"] is False
        return web.json_response({"status": "granted", "config": config})

    base_url = await local_server({"/claim/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    fakts = await ClaimEndpointClaimer().aclaim("tok", endpoint)
    assert isinstance(fakts, ActiveFakts)
    assert "test" in fakts.instances


async def test_claim_denied_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"status": "denied"})

    base_url = await local_server({"/claim/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    with pytest.raises(ClaimError, match="denied"):
        await ClaimEndpointClaimer().aclaim("tok", endpoint)


async def test_claim_error_status_propagates_message(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"status": "error", "message": "boom"})

    base_url = await local_server({"/claim/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    with pytest.raises(ClaimError, match="boom"):
        await ClaimEndpointClaimer().aclaim("tok", endpoint)


async def test_claim_unknown_status_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"status": "weird"})

    base_url = await local_server({"/claim/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    with pytest.raises(ClaimError, match="unexpected status"):
        await ClaimEndpointClaimer().aclaim("tok", endpoint)


async def test_claim_missing_status_field_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"config": {}})

    base_url = await local_server({"/claim/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    with pytest.raises(ClaimError, match="missing the 'status' field"):
        await ClaimEndpointClaimer().aclaim("tok", endpoint)


async def test_claim_non_200_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=500, text="server on fire")

    base_url = await local_server({"/claim/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    with pytest.raises(ClaimError, match="status code 500"):
        await ClaimEndpointClaimer().aclaim("tok", endpoint)


async def test_claim_200_non_json_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=200, text="not json", content_type="text/plain")

    base_url = await local_server({"/claim/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    with pytest.raises(ClaimError, match="not valid JSON"):
        await ClaimEndpointClaimer().aclaim("tok", endpoint)


# --------------------------------------------------------------------------- #
# RedeemDemander
# --------------------------------------------------------------------------- #


async def test_redeem_granted_returns_token(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        assert body["token"] == "redeem-token"
        assert body["manifest"]["identifier"] == "test_manifest"
        return web.json_response({"status": "granted", "token": "client-token"})

    base_url = await local_server({"/redeem/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    demander = RedeemDemander(manifest=make_manifest(), token="redeem-token")
    token = await demander.ademand(endpoint)
    assert token == "client-token"


async def test_redeem_error_status_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"status": "error", "message": "expired"})

    base_url = await local_server({"/redeem/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    demander = RedeemDemander(manifest=make_manifest(), token="redeem-token")
    with pytest.raises(RetrieveError, match="expired"):
        await demander.ademand(endpoint)


async def test_redeem_unknown_status_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"status": "weird"})

    base_url = await local_server({"/redeem/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    demander = RedeemDemander(manifest=make_manifest(), token="redeem-token")
    with pytest.raises(RetrieveError, match="unexpected status"):
        await demander.ademand(endpoint)


async def test_redeem_non_200_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=403, text="forbidden")

    base_url = await local_server({"/redeem/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    demander = RedeemDemander(manifest=make_manifest(), token="redeem-token")
    with pytest.raises(RetrieveError, match="status code 403"):
        await demander.ademand(endpoint)


async def test_redeem_missing_status_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"token": "client-token"})

    base_url = await local_server({"/redeem/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    demander = RedeemDemander(manifest=make_manifest(), token="redeem-token")
    with pytest.raises(RetrieveError, match="missing the 'status' field"):
        await demander.ademand(endpoint)


async def test_redeem_200_non_json_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=200, text="not json", content_type="text/plain")

    base_url = await local_server({"/redeem/": handler})
    endpoint = FaktsEndpoint(base_url=base_url, name="local")

    demander = RedeemDemander(manifest=make_manifest(), token="redeem-token")
    with pytest.raises(RetrieveError, match="not valid JSON"):
        await demander.ademand(endpoint)


async def test_redeem_url_override_takes_precedence(local_server) -> None:
    """An explicit retrieve_url on the demander beats both the endpoint's
    retrieve_url and the {base_url}redeem/ fallback."""
    seen: dict[str, bool] = {}

    async def handler(request: web.Request) -> web.Response:
        seen["hit"] = True
        return web.json_response({"status": "granted", "token": "client-token"})

    base_url = await local_server({"/custom/": handler})
    # endpoint base_url points nowhere useful; the override must win
    endpoint = FaktsEndpoint(base_url="http://127.0.0.1:1/", name="local")

    demander = RedeemDemander(
        manifest=make_manifest(),
        token="redeem-token",
        retrieve_url=f"{base_url}custom/",
    )
    token = await demander.ademand(endpoint)
    assert token == "client-token"
    assert seen.get("hit") is True


# --------------------------------------------------------------------------- #
# Discovery utils
# --------------------------------------------------------------------------- #


async def test_check_wellknown_valid(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"name": "MyServer", "base_url": "http://x/f/"})

    base_url = await local_server(
        {"/.well-known/fakts": handler}, method="GET"
    )
    import ssl

    endpoint = await check_wellknown(base_url, ssl.create_default_context())
    assert endpoint.name == "MyServer"


async def test_check_wellknown_missing_name_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"base_url": "http://x/f/"})

    base_url = await local_server(
        {"/.well-known/fakts": handler}, method="GET"
    )
    import ssl

    with pytest.raises(DiscoveryError, match="missing the required 'name' field"):
        await check_wellknown(base_url, ssl.create_default_context())


async def test_check_wellknown_non_json_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(text="<html>nope</html>", content_type="text/html")

    base_url = await local_server(
        {"/.well-known/fakts": handler}, method="GET"
    )
    import ssl

    with pytest.raises(DiscoveryError, match="not valid JSON"):
        await check_wellknown(base_url, ssl.create_default_context())


async def test_check_wellknown_non_200_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=404, text="nope")

    base_url = await local_server(
        {"/.well-known/fakts": handler}, method="GET"
    )
    import ssl

    with pytest.raises(DiscoveryError, match="status code 404"):
        await check_wellknown(base_url, ssl.create_default_context())


async def test_discover_url_with_protocol_and_slash_append(local_server) -> None:
    """A full URL (with protocol) is checked directly; allow_appending_slash
    normalises a missing trailing slash before hitting .well-known/fakts."""
    import ssl

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"name": "MyServer"})

    base_url = await local_server(
        {"/.well-known/fakts": handler}, method="GET"
    )
    # strip the trailing slash so allow_appending_slash has to re-add it
    no_slash = base_url.rstrip("/")

    endpoint = await discover_url(
        no_slash,
        ssl.create_default_context(),
        allow_appending_slash=True,
        timeout=2,
    )
    assert endpoint.name == "MyServer"


async def test_discover_url_no_protocol_without_auto_protocols_raises() -> None:
    import ssl

    with pytest.raises(DiscoveryError, match="does not specify a protocol"):
        await discover_url("localhost:8000", ssl.create_default_context())


async def test_discover_url_aggregates_protocol_errors() -> None:
    """With auto_protocols and no reachable server, every attempt fails and
    the errors are aggregated into a single DiscoveryError."""
    import ssl

    with pytest.raises(DiscoveryError, match="Could not connect via any protocol"):
        await discover_url(
            "127.0.0.1:1",
            ssl.create_default_context(),
            auto_protocols=["http"],
            timeout=1,
        )
