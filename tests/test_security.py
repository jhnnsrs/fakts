"""Where credentials may and may not go.

Each test pins a way a secret (refresh token, redeem token, device code) could
leak to a host it was not meant for, or reach one over a downgraded transport.
"""

import datetime
import ipaddress
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from aiohttp import web

from fakts.errors import FaktsError
from fakts.grants.remote.discovery.utils import check_wellknown, discover_url
from fakts.grants.remote.errors import DiscoveryError
from fakts.oauth2 import apost_form, apost_json

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@pytest_asyncio.fixture
async def server() -> AsyncIterator[Callable[[dict[str, Handler]], Awaitable[str]]]:
    """Start a local server with POST routes; returns its base url (no slash)."""
    runners = []

    async def start(routes: dict[str, Handler]) -> str:
        app = web.Application()
        for path, handler in routes.items():
            app.router.add_route("POST", path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        return f"http://127.0.0.1:{runner.addresses[0][1]}"

    yield start

    for runner in runners:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("post", [apost_form, apost_json])
async def test_a_credential_post_never_follows_a_redirect(server, status, post) -> None:
    """A redirect would resend the form body (307/308) to wherever it points."""
    stolen: list[dict] = []

    async def steal(request: web.Request) -> web.Response:
        stolen.append(dict(await request.post()) or await request.json())
        return web.json_response({"access_token": "x"})

    thief = await server({"/steal": steal})

    async def token(request: web.Request) -> web.Response:
        return web.Response(status=status, headers={"Location": f"{thief}/steal"})

    base = await server({"/token": token})

    with pytest.raises(FaktsError, match="redirect"):
        await post(
            f"{base}/token",
            {"refresh_token": "the-secret"},
            ssl_context=ssl.create_default_context(),
        )
    assert stolen == [], "the credential followed the redirect"


# --------------------------------------------------------------------------- #
# Discovery: where the well-known document may send the credential flow
# --------------------------------------------------------------------------- #


def _document(origin: str, token_origin: str | None = None) -> dict:
    token_origin = token_origin or origin
    return {
        "name": "Server",
        "base_url": f"{origin}/f/",
        "protocol_version": "2",
        "token_endpoint": f"{token_origin}/o/token/",
        "device_authorization_endpoint": f"{origin}/o/app-authorization/",
    }


@pytest_asyncio.fixture
async def wellknown() -> AsyncIterator[Callable[..., Awaitable[str]]]:
    """Serve a well-known document built from the server's own origin."""
    runners = []

    async def start(document, ssl_context: ssl.SSLContext | None = None) -> str:
        async def handler(request: web.Request) -> web.Response:
            return web.json_response(document(f"{request.scheme}://{request.host}"))

        app = web.Application()
        app.router.add_get("/.well-known/fakts", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=ssl_context)
        await site.start()
        runners.append(runner)
        return f"127.0.0.1:{runner.addresses[0][1]}"

    yield start

    for runner in runners:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_a_token_endpoint_on_another_origin_is_refused(wellknown) -> None:
    host = await wellknown(lambda origin: _document(origin, token_origin="https://evil.example"))

    with pytest.raises(DiscoveryError, match="another origin"):
        await check_wellknown(f"http://{host}/", ssl.create_default_context())

    # Opted into, for a deployment that really splits its hosts.
    endpoint = await check_wellknown(
        f"http://{host}/", ssl.create_default_context(), allow_cross_origin_endpoints=True
    )
    assert endpoint.token_endpoint == "https://evil.example/o/token/"


@pytest.mark.asyncio
async def test_a_null_token_endpoint_is_refused(wellknown) -> None:
    host = await wellknown(lambda origin: {**_document(origin), "token_endpoint": None})

    with pytest.raises(DiscoveryError, match="no 'token_endpoint'"):
        await check_wellknown(f"http://{host}/", ssl.create_default_context())


@pytest.mark.asyncio
async def test_a_plain_http_server_is_still_found_without_a_scheme(wellknown) -> None:
    """https against a plain-http dev server is a protocol mismatch: fall back."""
    host = await wellknown(_document)

    endpoint = await discover_url(
        f"{host}/", ssl.create_default_context(), auto_protocols=["https", "http"]
    )
    assert endpoint.token_endpoint == f"http://{host}/o/token/"


def _untrusted_tls_context() -> ssl.SSLContext:
    """A server context with a self-signed certificate nobody trusts."""
    import tempfile

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    with tempfile.TemporaryDirectory() as tmp:
        cert_file, key_file = f"{tmp}/cert.pem", f"{tmp}/key.pem"
        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(key_file, "wb") as f:
            f.write(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        context.load_cert_chain(cert_file, key_file)
    return context


@pytest.mark.asyncio
async def test_a_failed_certificate_check_does_not_fall_back_to_http(wellknown) -> None:
    pytest.importorskip("cryptography")
    host = await wellknown(_document, ssl_context=_untrusted_tls_context())

    with pytest.raises(DiscoveryError, match="TLS verification failed"):
        await discover_url(
            f"{host}/", ssl.create_default_context(), auto_protocols=["https", "http"]
        )


# --------------------------------------------------------------------------- #
# A refresh is authoritative about what the app may still reach
# --------------------------------------------------------------------------- #


def _refresh(previous, **members) -> "object":
    from fakts.oauth2 import TokenResponse, merge_token_response

    response = TokenResponse(
        access_token="a2", refresh_token="r2", client_id="test_client_id", **members
    )
    return merge_token_response(
        previous, response, token_endpoint="http://x/token", report_endpoint=None, skew=30
    )


def test_a_refresh_that_withdraws_every_service_withdraws_them() -> None:
    """Empty instances used to read as 'field omitted' and kept the old grants."""
    from .helpers import make_fakts_value

    previous = make_fakts_value()
    previous.statuses = {"test": "granted"}  # type: ignore[assignment]
    assert previous.instances

    withdrawn = _refresh(previous, instances={}, statuses={})
    assert withdrawn.instances == {}
    assert withdrawn.statuses == {}


def test_a_refresh_that_omits_the_members_keeps_them() -> None:
    from .helpers import make_fakts_value

    previous = make_fakts_value()
    previous.statuses = {"test": "granted"}  # type: ignore[assignment]

    kept = _refresh(previous)
    assert kept.instances.keys() == previous.instances.keys()
    assert kept.statuses == previous.statuses
