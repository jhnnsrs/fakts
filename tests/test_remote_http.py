"""Unit tests for the remote grant subsystem, exercised against a real local
``aiohttp.web`` server.

This mirrors the local-server pattern used by ``test_challenge.py`` rather
than mocking aiohttp, so the actual request/response handling is covered.
Everything here runs without a real fakts server.
"""

import ssl
from typing import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from aiohttp import web

from fakts_next.grants.remote.authorizers.device_code import (
    ClientKind,
    DeviceCodeAuthorizer,
)
from fakts_next.grants.remote.authorizers.redeem import RedeemAuthorizer
from fakts_next.grants.remote.authorizers.static import StaticAuthorizer
from fakts_next.grants.remote.discovery.utils import check_wellknown, discover_url
from fakts_next.grants.remote.errors import (
    DeviceCodeExpiredError,
    DeviceCodeTimeoutError,
    DiscoveryError,
    RetrieveError,
    UserDeniedError,
)
from fakts_next.grants.remote.models import FaktsEndpoint
from fakts_next.oauth2 import InsecureTransportError

from .test_fakts_behavior import make_manifest

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


def endpoint_for(base_url: str) -> FaktsEndpoint:
    return FaktsEndpoint(
        base_url=base_url,
        name="Test",
        protocol_version="2",
        issuer=base_url,
        token_endpoint=f"{base_url}o/token/",
        device_authorization_endpoint=f"{base_url}o/app-authorization/",
    )


TOKEN_BODY = {
    "access_token": "the_access_token",
    "refresh_token": "the_refresh_token",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "openid read",
    "client_id": "minted_client_id",
    "self": {
        "deployment_name": "test_deployment",
        "alias": {"id": "self", "host": "localhost", "port": 8000, "path": "lok"},
    },
    "instances": {
        "test": {
            "service": "test_service",
            "identifier": "1",
            "aliases": [{"id": "a", "host": "localhost", "port": 8000, "challenge": "ht"}],
            "challenge_key": None,
        }
    },
    "statuses": {"test": "granted"},
}


def collecting_sleeper(recorded: list) -> Callable[[float], Awaitable[None]]:
    async def sleeper(seconds: float) -> None:
        recorded.append(seconds)

    return sleeper


# --------------------------------------------------------------------------- #
# Device code authorizer
# --------------------------------------------------------------------------- #


async def test_device_code_happy_path(local_server, monkeypatch) -> None:
    """The full flow: register, poll once, return tokens and config."""
    opened: list[str] = []
    monkeypatch.setattr(
        "webbrowser.open_new", lambda url: opened.append(url) or True
    )

    async def authorize(request: web.Request) -> web.Response:
        body = await request.json()
        # The manifest travels as a nested object, not a JSON string.
        assert body["manifest"]["identifier"] == "test_manifest"
        assert body["requested_client_kind"] == "development"
        assert body["requested_client_role"] == "interface"
        return web.json_response(
            {
                "status": "granted",
                "device_code": "dev_code",
                "user_code": "USERCODE",
                "client_id": "minted_client_id",
                "verification_uri": "http://example.com/configure/",
                "verification_uri_complete": "http://example.com/configure/USERCODE",
                "expires_in": 300,
                "interval": 1,
            }
        )

    async def token(request: web.Request) -> web.Response:
        form = await request.post()
        assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
        assert form["device_code"] == "dev_code"
        assert form["client_id"] == "minted_client_id"
        return web.json_response(TOKEN_BODY)

    base_url = await local_server(
        {"/o/app-authorization/": authorize, "/o/token/": token}
    )

    seen_codes: list[str] = []

    async def hook(endpoint: FaktsEndpoint, code: str) -> None:
        seen_codes.append(code)

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(),
        device_code_hook=hook,
        sleeper=collecting_sleeper([]),
        allow_insecure_transport=True,
    )

    response = await authorizer.aauthorize(endpoint_for(base_url))

    assert response.access_token == "the_access_token"
    assert response.refresh_token == "the_refresh_token"
    assert response.client_id == "minted_client_id"
    assert response.statuses["test"].value == "granted"
    assert seen_codes == ["USERCODE"]
    assert opened == ["http://example.com/configure/USERCODE"], (
        "The browser must open the server-supplied complete URL, not a derived one"
    )


async def test_device_code_polls_while_pending(local_server) -> None:
    """authorization_pending keeps the loop going without escalating."""
    calls = {"n": 0}

    async def authorize(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "granted",
                "device_code": "dev_code",
                "user_code": "CODE",
                "client_id": "cid",
                "verification_uri_complete": "http://example.com/x",
                "expires_in": 300,
                "interval": 1,
            }
        )

    async def token(request: web.Request) -> web.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return web.json_response({"error": "authorization_pending"}, status=400)
        return web.json_response(TOKEN_BODY)

    base_url = await local_server(
        {"/o/app-authorization/": authorize, "/o/token/": token}
    )

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(),
        open_browser=False,
        sleeper=collecting_sleeper([]),
        allow_insecure_transport=True,
    )
    response = await authorizer.aauthorize(endpoint_for(base_url))

    assert response.access_token == "the_access_token"
    assert calls["n"] == 3


async def test_device_code_slow_down_backs_off(local_server) -> None:
    """slow_down must widen the interval, not just retry at the same rate."""
    slept: list[float] = []
    calls = {"n": 0}

    async def authorize(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "granted",
                "device_code": "dev_code",
                "user_code": "CODE",
                "client_id": "cid",
                "verification_uri_complete": "http://example.com/x",
                "expires_in": 300,
                "interval": 5,
            }
        )

    async def token(request: web.Request) -> web.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return web.json_response({"error": "slow_down"}, status=400)
        return web.json_response(TOKEN_BODY)

    base_url = await local_server(
        {"/o/app-authorization/": authorize, "/o/token/": token}
    )

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(),
        open_browser=False,
        sleeper=collecting_sleeper(slept),
        allow_insecure_transport=True,
    )
    await authorizer.aauthorize(endpoint_for(base_url))

    assert slept == [5, 10], f"expected the interval to grow by 5, got {slept}"


async def test_device_code_access_denied_raises_user_denied(local_server) -> None:
    """A refusal is a legitimate outcome and gets its own catchable error."""

    async def authorize(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "granted",
                "device_code": "dev_code",
                "user_code": "CODE",
                "client_id": "cid",
                "verification_uri_complete": "http://example.com/x",
                "expires_in": 300,
                "interval": 1,
            }
        )

    async def token(request: web.Request) -> web.Response:
        return web.json_response({"error": "access_denied"}, status=400)

    base_url = await local_server(
        {"/o/app-authorization/": authorize, "/o/token/": token}
    )

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(),
        open_browser=False,
        sleeper=collecting_sleeper([]),
        allow_insecure_transport=True,
    )

    with pytest.raises(UserDeniedError):
        await authorizer.aauthorize(endpoint_for(base_url))


async def test_device_code_expired_token_raises_expired(local_server) -> None:
    async def authorize(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "granted",
                "device_code": "dev_code",
                "user_code": "CODE",
                "client_id": "cid",
                "verification_uri_complete": "http://example.com/x",
                "expires_in": 300,
                "interval": 1,
            }
        )

    async def token(request: web.Request) -> web.Response:
        return web.json_response({"error": "expired_token"}, status=400)

    base_url = await local_server(
        {"/o/app-authorization/": authorize, "/o/token/": token}
    )

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(),
        open_browser=False,
        sleeper=collecting_sleeper([]),
        allow_insecure_transport=True,
    )

    with pytest.raises(DeviceCodeExpiredError):
        await authorizer.aauthorize(endpoint_for(base_url))


async def test_device_code_client_deadline_raises_timeout(local_server) -> None:
    """The client's own deadline is distinct from the server expiring the code."""

    async def authorize(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "granted",
                "device_code": "dev_code",
                "user_code": "CODE",
                "client_id": "cid",
                "verification_uri_complete": "http://example.com/x",
                "expires_in": 300,
                "interval": 1,
            }
        )

    async def token(request: web.Request) -> web.Response:
        return web.json_response({"error": "authorization_pending"}, status=400)

    base_url = await local_server(
        {"/o/app-authorization/": authorize, "/o/token/": token}
    )

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(),
        open_browser=False,
        timeout=3,
        sleeper=collecting_sleeper([]),
        allow_insecure_transport=True,
    )

    with pytest.raises(DeviceCodeTimeoutError):
        await authorizer.aauthorize(endpoint_for(base_url))


async def test_device_authorization_error_envelope_is_surfaced(local_server) -> None:
    """The device endpoint reports failure inside a 200 body, which must not
    be mistaken for success."""

    async def authorize(request: web.Request) -> web.Response:
        return web.json_response({"status": "error", "error": "Malformed request: x"})

    base_url = await local_server({"/o/app-authorization/": authorize})

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(),
        open_browser=False,
        sleeper=collecting_sleeper([]),
        allow_insecure_transport=True,
    )

    with pytest.raises(Exception, match="Malformed request"):
        await authorizer.aauthorize(endpoint_for(base_url))


async def test_device_authorization_throttle_is_surfaced(local_server) -> None:
    """Throttling answers 429 with a bare error and no status key."""

    async def authorize(request: web.Request) -> web.Response:
        return web.json_response({"error": "slow_down"}, status=429)

    base_url = await local_server({"/o/app-authorization/": authorize})

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(),
        open_browser=False,
        sleeper=collecting_sleeper([]),
        allow_insecure_transport=True,
    )

    with pytest.raises(Exception, match="slow_down"):
        await authorizer.aauthorize(endpoint_for(base_url))


# --------------------------------------------------------------------------- #
# Redeem authorizer
# --------------------------------------------------------------------------- #


async def test_redeem_returns_session(local_server) -> None:
    async def token(request: web.Request) -> web.Response:
        form = await request.post()
        assert form["grant_type"] == "urn:fakts:grant-type:redeem"
        assert form["redeem_token"] == "my_redeem_token"
        # Here the manifest is a JSON *string*, unlike device authorization.
        import json as _json

        assert _json.loads(form["manifest"])["identifier"] == "test_manifest"
        return web.json_response(TOKEN_BODY)

    base_url = await local_server({"/o/token/": token})

    authorizer = RedeemAuthorizer(
        manifest=make_manifest(),
        token="my_redeem_token",
        allow_insecure_transport=True,
    )
    response = await authorizer.aauthorize(endpoint_for(base_url))

    assert response.refresh_token == "the_refresh_token"


async def test_redeem_rejected_raises_retrieve_error(local_server) -> None:
    async def token(request: web.Request) -> web.Response:
        return web.json_response(
            {"error": "invalid_grant", "error_description": "allow_reredeem"},
            status=400,
        )

    base_url = await local_server({"/o/token/": token})

    authorizer = RedeemAuthorizer(
        manifest=make_manifest(),
        token="spent",
        allow_insecure_transport=True,
    )

    with pytest.raises(RetrieveError, match="invalid_grant"):
        await authorizer.aauthorize(endpoint_for(base_url))


async def test_redeem_is_not_interactive() -> None:
    """Non-interactive grants may be re-run unattended, which is what keeps
    headless deployments recoverable."""
    authorizer = RedeemAuthorizer(manifest=make_manifest(), token="t")
    assert authorizer.requires_user_interaction is False


# --------------------------------------------------------------------------- #
# Static authorizer
# --------------------------------------------------------------------------- #


async def test_static_authorizer_refreshes_compound_credential(local_server) -> None:
    async def token(request: web.Request) -> web.Response:
        form = await request.post()
        assert form["grant_type"] == "refresh_token"
        assert form["client_id"] == "cid"
        assert form["refresh_token"] == "rtok"
        return web.json_response(TOKEN_BODY)

    base_url = await local_server({"/o/token/": token})

    authorizer = StaticAuthorizer(token="cid:rtok", allow_insecure_transport=True)
    response = await authorizer.aauthorize(endpoint_for(base_url))

    assert response.access_token == "the_access_token"


async def test_static_authorizer_rejects_bare_token() -> None:
    """A bare refresh token cannot work: the token endpoint authenticates the
    client before it looks at the token."""
    authorizer = StaticAuthorizer(token="just_a_refresh_token")

    with pytest.raises(RetrieveError, match="client_id:refresh_token"):
        await authorizer.aauthorize(endpoint_for("http://127.0.0.1:1/"))


# --------------------------------------------------------------------------- #
# Transport opt-in
# --------------------------------------------------------------------------- #


async def test_plain_http_to_network_host_requires_opt_in() -> None:
    """Credentials must not leave over cleartext to a non-loopback host
    unless that was explicitly chosen."""
    endpoint = FaktsEndpoint(
        base_url="http://some-lan-box:8000/f/",
        name="LAN",
        protocol_version="2",
        token_endpoint="http://some-lan-box:8000/o/token/",
        device_authorization_endpoint="http://some-lan-box:8000/o/app-authorization/",
    )
    authorizer = DeviceCodeAuthorizer(manifest=make_manifest(), open_browser=False)

    with pytest.raises(InsecureTransportError, match="allow_insecure_transport"):
        await authorizer.aauthorize(endpoint)


async def test_plain_http_to_loopback_needs_no_opt_in(local_server) -> None:
    """Loopback is always allowed, matching the server's own rule, so local
    development needs no ceremony."""

    async def token(request: web.Request) -> web.Response:
        return web.json_response(TOKEN_BODY)

    base_url = await local_server({"/o/token/": token})

    authorizer = StaticAuthorizer(token="cid:rtok")
    response = await authorizer.aauthorize(endpoint_for(base_url))

    assert response.access_token == "the_access_token"


async def test_insecure_transport_env_var_opts_in(monkeypatch) -> None:
    """Containers that cannot pass a keyword argument use the env var."""
    from fakts_next import oauth2

    monkeypatch.setenv("FAKTS_ALLOW_INSECURE_TRANSPORT", "1")
    # Must not raise.
    oauth2.check_transport("http://some-lan-box:8000/o/token/", False)


# --------------------------------------------------------------------------- #
# Discovery utils
# --------------------------------------------------------------------------- #


def v2_document(base_url: str = "http://x/f/") -> dict:
    return {
        "name": "MyServer",
        "base_url": base_url,
        "protocol_version": "2",
        "issuer": "http://x",
        "token_endpoint": "http://x/o/token/",
        "device_authorization_endpoint": "http://x/o/app-authorization/",
    }


async def test_check_wellknown_valid(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response(v2_document())

    base_url = await local_server({"/.well-known/fakts": handler}, method="GET")

    endpoint = await check_wellknown(base_url, ssl.create_default_context())
    assert endpoint.name == "MyServer"
    assert endpoint.token_endpoint == "http://x/o/token/"


async def test_check_wellknown_preserves_unmodelled_members(local_server) -> None:
    """The document also carries mesh_*/hub_* members other tools read off
    the same fetch, so they must survive validation."""

    async def handler(request: web.Request) -> web.Response:
        doc = v2_document()
        doc["mesh_coord_url"] = "http://x/mesh"
        return web.json_response(doc)

    base_url = await local_server({"/.well-known/fakts": handler}, method="GET")

    endpoint = await check_wellknown(base_url, ssl.create_default_context())
    assert endpoint.mesh_coord_url == "http://x/mesh"


async def test_check_wellknown_v1_server_names_the_protocol(local_server) -> None:
    """A v1 server must fail with a version error, not an obscure symptom
    further down the flow."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response(
            {"name": "OldServer", "base_url": "http://x/f/", "claim": "http://x/f/claim/"}
        )

    base_url = await local_server({"/.well-known/fakts": handler}, method="GET")

    with pytest.raises(DiscoveryError, match="protocol version 1"):
        await check_wellknown(base_url, ssl.create_default_context())


async def test_check_wellknown_v2_without_token_endpoint_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response(
            {"name": "Broken", "base_url": "http://x/f/", "protocol_version": "2"}
        )

    base_url = await local_server({"/.well-known/fakts": handler}, method="GET")

    with pytest.raises(DiscoveryError, match="no 'token_endpoint'"):
        await check_wellknown(base_url, ssl.create_default_context())


async def test_check_wellknown_missing_name_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"base_url": "http://x/f/"})

    base_url = await local_server({"/.well-known/fakts": handler}, method="GET")

    with pytest.raises(DiscoveryError, match="missing the required 'name' field"):
        await check_wellknown(base_url, ssl.create_default_context())


async def test_check_wellknown_non_json_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(text="<html>nope</html>", content_type="text/html")

    base_url = await local_server({"/.well-known/fakts": handler}, method="GET")

    with pytest.raises(DiscoveryError, match="not valid JSON"):
        await check_wellknown(base_url, ssl.create_default_context())


async def test_check_wellknown_non_200_raises(local_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=404, text="nope")

    base_url = await local_server({"/.well-known/fakts": handler}, method="GET")

    with pytest.raises(DiscoveryError, match="status code 404"):
        await check_wellknown(base_url, ssl.create_default_context())


async def test_discover_url_with_protocol_and_slash_append(local_server) -> None:
    """A full URL (with protocol) is checked directly; allow_appending_slash
    normalises a missing trailing slash before hitting .well-known/fakts."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response(v2_document())

    base_url = await local_server({"/.well-known/fakts": handler}, method="GET")
    no_slash = base_url.rstrip("/")

    endpoint = await discover_url(
        no_slash,
        ssl.create_default_context(),
        allow_appending_slash=True,
        timeout=2,
    )
    assert endpoint.name == "MyServer"


async def test_discover_url_no_protocol_without_auto_protocols_raises() -> None:
    with pytest.raises(DiscoveryError, match="does not specify a protocol"):
        await discover_url("localhost:8000", ssl.create_default_context())


async def test_discover_url_aggregates_protocol_errors() -> None:
    """With auto_protocols and no reachable server, every attempt fails and
    the errors are aggregated into a single DiscoveryError."""
    with pytest.raises(DiscoveryError, match="Could not connect via any protocol"):
        await discover_url(
            "127.0.0.1:1",
            ssl.create_default_context(),
            auto_protocols=["http"],
            timeout=1,
        )
