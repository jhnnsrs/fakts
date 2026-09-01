"""Regression tests for the audit findings.

Each of these asserts a specific failure mode that was verified to exist
before the fix. They are grouped by what they protect, not by module.
"""

import asyncio
import os
import ssl
import stat
import time
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional

import pytest
import pytest_asyncio
from aiohttp import web
from pydantic import BaseModel

from fakts_next import Fakts
from fakts_next.cache.file import FileCache
from fakts_next.errors import NeedsReauthenticationError
from fakts_next.grants.env import EnvGrant
from fakts_next.grants.hard import HardFaktsGrant
from fakts_next.grants.remote.authorizers.device_code import DeviceCodeAuthorizer
from fakts_next.models import (
    ActiveFakts,
    Alias,
    AuthFakt,
    ChallengeKey,
    Instance,
    Manifest,
    PublicSource,
    Requirement,
    SelfFakt,
)
from fakts_next.oauth2 import InsecureTransportError, check_transport

from .test_fakts_behavior import make_fakts_value, make_manifest

pytestmark = pytest.mark.asyncio


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@pytest_asyncio.fixture
async def server() -> AsyncIterator[Callable[..., Awaitable[str]]]:
    runners = []

    async def start(routes: dict[str, Handler], method: str = "GET") -> str:
        app = web.Application()
        for path, handler in routes.items():
            app.router.add_route(method, path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        return f"http://127.0.0.1:{runner.addresses[0][1]}"

    yield start

    for runner in runners:
        await runner.cleanup()


class Grant(BaseModel):
    fakts: ActiveFakts
    load_count: int = 0
    requires_user_interaction: bool = True

    async def aload(self) -> ActiveFakts:
        self.load_count += 1
        return self.fakts


# --------------------------------------------------------------------------- #
# Alias challenge integrity
# --------------------------------------------------------------------------- #


async def test_challenge_does_not_follow_redirects(server) -> None:
    """The signed message commits only to the nonce, so a host that bounces
    the probe to the real service would have it sign our nonce and pass.
    Refusing redirects removes the zero-effort version of that."""
    signed_by_real_service = {"hit": False}

    async def impostor(request: web.Request) -> web.Response:
        nonce = request.query.get("nonce", "")
        raise web.HTTPFound(f"/real?nonce={nonce}")

    async def real(request: web.Request) -> web.Response:
        signed_by_real_service["hit"] = True
        return web.json_response({"signature": "whatever"})

    base = await server({"/challenge": impostor, "/real": real})
    port = int(base.rsplit(":", 1)[1])

    fakts = Fakts(grant=Grant(fakts=make_fakts_value()), manifest=make_manifest())
    alias = Alias(id="a", host="127.0.0.1", port=port, challenge="challenge")

    async with fakts:
        with pytest.raises(Exception):
            await fakts.achallenge_alias(alias)

    assert not signed_by_real_service["hit"], (
        "the probe was relayed to the genuine service — a redirector could "
        "satisfy the challenge and still receive all the traffic"
    )


async def test_omit_challenge_does_not_disable_later_verification(
    monkeypatch,
) -> None:
    """One omit_challenge=True call used to poison the alias cache for the
    whole process, skipping the pinned-key check for every later caller."""
    challenged: list[str] = []

    async def fake_challenge(self, alias, challenge_key=None) -> bool:
        challenged.append(alias.id)
        return True

    monkeypatch.setattr(Fakts, "achallenge_alias", fake_challenge)

    value = make_fakts_value()
    value.instances["test"].challenge_key = ChallengeKey(kind="ed25519", key="AAAA")

    fakts = Fakts(grant=Grant(fakts=value), manifest=make_manifest())

    async with fakts:
        await fakts.aget_alias("test", omit_challenge=True, omit_report=True)
        assert challenged == [], "omit_challenge must not probe"

        await fakts.aget_alias("test", omit_report=True)
        assert challenged, "a caller that wants a challenge must get one"

        before = len(challenged)
        await fakts.aget_alias("test", omit_report=True)
        assert len(challenged) == before, "a challenged alias should still cache"


# --------------------------------------------------------------------------- #
# Credential disclosure
# --------------------------------------------------------------------------- #


async def test_cache_load_error_does_not_log_the_token(tmp_path: Path, caplog) -> None:
    """A corrupt cache is logged on every start; the log must not carry the
    credential that made it corrupt."""
    secret = "v1.SUPERSECRET_REFRESH_TOKEN_ABCDEFGHIJKLMNOP"
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        '{"fakts": {"self": {"deployment_name": "d", "alias": {"id": "a", "host": "h"}},'
        ' "auth": {"client_id": "c", "refresh_token": "' + secret + '"},'
        ' "instances": {}, "statuses": {}}, "created": "2026-01-01T00:00:00", "hash": ""}'
    )

    with caplog.at_level("DEBUG"):
        assert await FileCache(cache_file=str(cache_file)).aload() is None

    assert secret not in caplog.text


# --------------------------------------------------------------------------- #
# Transport gating
# --------------------------------------------------------------------------- #


async def test_insecure_transport_env_var_respects_falsey_values(monkeypatch) -> None:
    """FAKTS_ALLOW_INSECURE_TRANSPORT=0 must not *enable* insecure transport."""
    url = "http://some-lan-box:8000/o/token/"

    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("FAKTS_ALLOW_INSECURE_TRANSPORT", value)
        with pytest.raises(InsecureTransportError):
            check_transport(url, False)

    monkeypatch.setenv("FAKTS_ALLOW_INSECURE_TRANSPORT", "1")
    check_transport(url, False)  # must not raise


async def test_report_is_skipped_over_untrusted_transport(monkeypatch) -> None:
    """The report carries the access token, so it gets the same gate as the
    token endpoint. It used to be the one credential-bearing call without one."""
    import aiohttp

    posted: list[str] = []
    real_post = aiohttp.ClientSession.post

    def spy(self, url, *args, **kwargs):
        posted.append(str(url))
        return real_post(self, url, *args, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "post", spy)

    # Same origin as the token endpoint, so *only* the transport gate can
    # stop this — otherwise the origin check would mask it.
    value = make_fakts_value()
    value.auth.token_endpoint = "http://some-lan-box:8000/o/token/"
    value.auth.report_endpoint = "http://some-lan-box:8000/f/report/"

    fakts = Fakts(grant=Grant(fakts=value), manifest=make_manifest())
    async with fakts:
        await fakts._areport_aliases(value, [], "an-access-token")

    assert posted == [], f"the access token was sent over plain http: {posted}"


async def test_report_over_https_is_sent(monkeypatch) -> None:
    """The gate must not simply disable reporting everywhere."""
    import aiohttp

    posted: list[str] = []
    real_post = aiohttp.ClientSession.post

    def spy(self, url, *args, **kwargs):
        posted.append(str(url))
        return real_post(self, url, *args, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "post", spy)

    value = make_fakts_value()
    value.auth.token_endpoint = "https://example.com/o/token/"
    value.auth.report_endpoint = "https://example.com/f/report/"

    fakts = Fakts(grant=Grant(fakts=value), manifest=make_manifest())
    async with fakts:
        await fakts._areport_aliases(value, [], "an-access-token")

    assert posted == ["https://example.com/f/report/"]


async def test_report_is_skipped_when_origin_differs() -> None:
    """A report endpoint on a different origin than the token endpoint would
    send the bearer token somewhere the app never authenticated against."""
    value = make_fakts_value()
    value.auth.token_endpoint = "https://real.example.com/o/token/"
    value.auth.report_endpoint = "https://attacker.example.com/f/report/"

    fakts = Fakts(grant=Grant(fakts=value), manifest=make_manifest())
    async with fakts:
        # Reaches the origin check and returns without attempting a request.
        await fakts._areport_aliases(value, [], "an-access-token")


@pytest.mark.parametrize(
    "uri,should_open",
    [
        ("https://example.com/configure/ABC", True),
        ("http://example.com/configure/ABC", True),
        ("file:///etc/passwd", False),
        ("javascript:alert(1)", False),
        ("customscheme://do-something", False),
    ],
)
async def test_browser_only_opens_http_urls(server, monkeypatch, uri, should_open) -> None:
    """webbrowser hands unknown schemes to the desktop's handler, so a
    hostile endpoint could otherwise get file:// invoked."""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open_new", lambda url: opened.append(url))

    async def authorize(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "granted",
                "device_code": "d",
                "user_code": "U",
                "client_id": "c",
                "verification_uri_complete": uri,
                "expires_in": 1,
                "interval": 1,
            }
        )

    async def token(request: web.Request) -> web.Response:
        return web.json_response({"error": "access_denied"}, status=400)

    base = await server(
        {"/o/app-authorization/": authorize, "/o/token/": token}, method="POST"
    )

    from fakts_next.grants.remote.errors import UserDeniedError
    from fakts_next.grants.remote.models import FaktsEndpoint

    endpoint = FaktsEndpoint(
        base_url=base + "/",
        name="T",
        protocol_version="2",
        token_endpoint=f"{base}/o/token/",
        device_authorization_endpoint=f"{base}/o/app-authorization/",
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(), sleeper=no_sleep, allow_insecure_transport=True
    )

    with pytest.raises(UserDeniedError):
        await authorizer.aauthorize(endpoint)

    assert (opened == [uri]) is should_open, f"opened={opened} for {uri}"


# --------------------------------------------------------------------------- #
# Cache trust
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics")
async def test_world_writable_cache_is_refused(tmp_path: Path) -> None:
    """The cache names the token endpoint. Anything that can write it can
    redirect the refresh token."""
    cache_file = tmp_path / "cache.json"
    cache = FileCache(cache_file=str(cache_file))
    await cache.aset(make_fakts_value())

    assert await cache.aload() is not None, "a private cache must still load"

    os.chmod(cache_file, 0o666)
    assert await cache.aload() is None, "a world-writable cache must be refused"


# --------------------------------------------------------------------------- #
# Unattended recovery
# --------------------------------------------------------------------------- #


async def test_env_and_hard_grants_are_non_interactive() -> None:
    """Without this, a container gets 'needs someone at a browser' for a
    credential it could simply have re-read."""
    assert EnvGrant().requires_user_interaction is False
    assert HardFaktsGrant(fakts=make_fakts_value()).requires_user_interaction is False


async def test_hard_grant_does_not_hand_out_its_own_object() -> None:
    """Alias reordering mutates in place, so returning the caller's object
    lets one Fakts reorder another's configuration."""
    value = make_fakts_value()
    grant = HardFaktsGrant(fakts=value)
    loaded = await grant.aload()
    loaded.instances["test"].aliases.reverse()
    assert value.instances["test"].aliases[0].id == "primary"


async def test_env_grant_recovers_unattended_when_credential_ages(
    monkeypatch, tmp_path: Path
) -> None:
    """An aged env credential must reload from the environment rather than
    raise — that is the whole headless story."""
    import json

    from fakts_next.fakts import REFRESH_TOKEN_MAX_AGE

    fresh = make_fakts_value(refresh_token="from_env")
    fresh.auth.refresh_issued_at = time.time()
    fresh.auth.token_endpoint = "https://example.com/o/token/"

    path = tmp_path / "fakts.json"
    path.write_text(fresh.model_dump_json())
    monkeypatch.delenv("FAKTS", raising=False)
    monkeypatch.setenv("FAKTS_FILE", str(path))

    aged = make_fakts_value(refresh_token="aged")
    aged.auth.refresh_issued_at = time.time() - REFRESH_TOKEN_MAX_AGE - 60
    aged.auth.access_token = None

    fakts = Fakts(grant=EnvGrant(), manifest=make_manifest())
    async with fakts:
        fakts.loaded_fakts = aged
        # Must not raise NeedsReauthenticationError: the grant is unattended.
        try:
            await fakts.aget_token()
        except NeedsReauthenticationError:
            pytest.fail("a non-interactive grant must recover without a human")
        except Exception:
            # A network failure reaching the (fake) token endpoint is fine —
            # what matters is that we got past the interactive gate.
            pass


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


async def test_fakts_is_unusable_after_exit() -> None:
    from fakts_next.errors import NotEnteredError

    fakts = Fakts(grant=Grant(fakts=make_fakts_value()), manifest=make_manifest())
    async with fakts:
        await fakts.aload()

    with pytest.raises(NotEnteredError):
        await fakts.aget_alias("test", omit_challenge=True, omit_report=True)


async def test_failed_enter_does_not_leak_the_context_variable() -> None:
    from fakts_next import get_current_fakts_next
    from fakts_next.errors import NoFaktsFound

    class StaticGrant(BaseModel):
        requires_user_interaction: bool = False

        async def aload(self) -> ActiveFakts:
            return make_fakts_value()

    class ExplodingCache(BaseModel):
        """Fails when __aenter__ binds the manifest hash to it.

        The grant no longer runs on enter, so the cache-hash binding is the
        remaining step that can fail after the contextvar is already set —
        which is the condition this test exists to pin.
        """

        hash: str = ""

        def __setattr__(self, name: str, value: object) -> None:
            if name == "hash":
                raise RuntimeError("cache exploded")
            super().__setattr__(name, value)

        async def aload(self) -> None:
            return None

        async def aset(self, value: ActiveFakts) -> None: ...

        async def areset(self) -> None: ...

    fakts = Fakts(
        grant=StaticGrant(), cache=ExplodingCache(), manifest=make_manifest()
    )
    with pytest.raises(RuntimeError):
        async with fakts:
            pass

    with pytest.raises(NoFaktsFound):
        get_current_fakts_next()


# --------------------------------------------------------------------------- #
# Manifest hashing
# --------------------------------------------------------------------------- #


async def test_manifest_hash_tolerates_absent_requirements() -> None:
    """Reachable from __aenter__, so this used to crash at startup."""
    Manifest(version="1", identifier="a", scopes=[], requirements=None).hash()


async def test_manifest_hash_is_order_independent() -> None:
    """Order-sensitivity would invalidate the cache and re-prompt the user
    for a manifest that did not actually change."""
    a = Manifest(
        version="1",
        identifier="app",
        scopes=["x", "y"],
        requirements=[
            Requirement(key="r1", service="s1"),
            Requirement(key="r2", service="s2"),
        ],
        public_sources=[
            PublicSource(kind="k1", url="u1"),
            PublicSource(kind="k2", url="u2"),
        ],
    )
    b = Manifest(
        version="1",
        identifier="app",
        scopes=["y", "x"],
        requirements=[
            Requirement(key="r2", service="s2"),
            Requirement(key="r1", service="s1"),
        ],
        public_sources=[
            PublicSource(kind="k2", url="u2"),
            PublicSource(kind="k1", url="u1"),
        ],
    )
    assert a.hash() == b.hash()
