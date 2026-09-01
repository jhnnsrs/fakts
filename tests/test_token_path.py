"""Tests for the OAuth2 token path: renewal, rotation, and the failure modes
that only appear when several processes share one cache.

This is the part of the client that holds a live credential, so most of
these are about *not* losing or leaking it rather than about happy paths.
"""

import asyncio
import os
import time
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional

import pytest
import pytest_asyncio
from aiohttp import web
from pydantic import BaseModel

from fakts_next import Fakts, ReauthPolicy
from fakts_next.cache.file import FileCache
from fakts_next.errors import NeedsReauthenticationError
from fakts_next.fakts import REFRESH_CHAIN_MAX_AGE, REFRESH_TOKEN_MAX_AGE
from fakts_next.models import ActiveFakts
from fakts_next.oauth2 import resolve_expiry

from .test_fakts_behavior import make_fakts_value, make_manifest

pytestmark = pytest.mark.asyncio


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@pytest_asyncio.fixture
async def token_server() -> AsyncIterator[Callable[..., Awaitable[str]]]:
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


class StaticGrant(BaseModel):
    """A grant that hands back a fixed configuration."""

    fakts: ActiveFakts
    load_count: int = 0
    requires_user_interaction: bool = True

    async def aload(self) -> ActiveFakts:
        self.load_count += 1
        return self.fakts


class MemoryCache(BaseModel):
    value: Optional[ActiveFakts] = None
    hash: str = ""
    set_count: int = 0

    async def aload(self) -> Optional[ActiveFakts]:
        return self.value

    async def aset(self, value: ActiveFakts) -> None:
        self.value = value.model_copy(deep=True)
        self.set_count += 1

    async def areset(self) -> None:
        self.value = None


def token_body(access: str, refresh: str, expires_in: int = 3600) -> dict:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": "openid",
        "client_id": "test_client_id",
        "self": {
            "deployment_name": "test_deployment",
            "alias": {"id": "self", "host": "localhost", "port": 8000, "path": "/self"},
        },
        "instances": {
            "test": {
                "service": "test_service",
                "identifier": "1",
                "aliases": [
                    {"id": "primary", "host": "localhost", "port": 8000, "path": "/test"},
                    {"id": "fallback", "host": "localhost", "port": 8001, "path": "/test"},
                ],
            }
        },
        "statuses": {"test": "granted"},
    }


def fakts_pointing_at(token_endpoint: str, **kwargs) -> ActiveFakts:
    value = make_fakts_value(**kwargs)
    value.auth.token_endpoint = token_endpoint
    value.auth.refresh_issued_at = time.time()
    value.auth.chain_started_at = time.time()
    return value


# --------------------------------------------------------------------------- #
# Renewal and rotation
# --------------------------------------------------------------------------- #


async def test_refresh_rotates_and_persists_before_use(token_server) -> None:
    """A rotated refresh token must reach the cache. The server has already
    revoked the old one by the time it answers, so anything we fail to
    persist is simply lost."""

    async def handler(request: web.Request) -> web.Response:
        form = await request.post()
        assert form["grant_type"] == "refresh_token"
        assert form["refresh_token"] == "original_token"
        assert form["client_id"] == "test_client_id"
        return web.json_response(token_body("new_access", "rotated_token"))

    endpoint = await token_server(handler)
    value = fakts_pointing_at(endpoint, refresh_token="original_token")

    cache = MemoryCache()
    fakts = Fakts(grant=StaticGrant(fakts=value), cache=cache, manifest=make_manifest())

    async with fakts:
        token = await fakts.aget_token()

    assert token == "new_access"
    assert cache.value is not None
    assert cache.value.auth.refresh_token == "rotated_token"
    assert cache.value.auth.access_token == "new_access"


async def test_cached_access_token_is_reused_without_refreshing(token_server) -> None:
    """The main defence against a refresh stampede: a still-valid access
    token from the cache is used as-is, so parallel starts do not all rotate."""
    calls = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        calls["n"] += 1
        return web.json_response(token_body("fresh", "rotated"))

    endpoint = await token_server(handler)
    value = fakts_pointing_at(
        endpoint,
        access_token="still_good",
        expires_at=time.time() + 3600,
    )

    cache = MemoryCache(value=value)
    fakts = Fakts(
        grant=StaticGrant(fakts=value), cache=cache, manifest=make_manifest()
    )

    async with fakts:
        token = await fakts.aget_token()

    assert token == "still_good"
    assert calls["n"] == 0, "A valid cached access token must not trigger a renewal"


async def test_expired_access_token_triggers_refresh(token_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response(token_body("fresh", "rotated"))

    endpoint = await token_server(handler)
    value = fakts_pointing_at(
        endpoint,
        access_token="expired",
        expires_at=time.time() - 10,
    )

    fakts = Fakts(
        grant=StaticGrant(fakts=value), cache=MemoryCache(), manifest=make_manifest()
    )

    async with fakts:
        assert await fakts.aget_token() == "fresh"


async def test_invalid_grant_adopts_sibling_credential(token_server) -> None:
    """The rotation race: another process rotated first and wrote the result.
    Adopting it is what keeps a herd converging instead of each member
    re-running the grant and deleting the others' client."""
    seen: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        form = await request.post()
        token = str(form["refresh_token"])
        seen.append(token)
        if token == "stale_token":
            return web.json_response({"error": "invalid_grant"}, status=400)
        return web.json_response(token_body("access_via_sibling", "rotated_again"))

    endpoint = await token_server(handler)

    ours = fakts_pointing_at(endpoint, refresh_token="stale_token")
    theirs = fakts_pointing_at(endpoint, refresh_token="sibling_token")

    grant = StaticGrant(fakts=ours)
    cache = MemoryCache(value=theirs)
    fakts = Fakts(grant=grant, cache=cache, manifest=make_manifest())

    async with fakts:
        fakts.loaded_fakts = ours
        token = await fakts.aget_token()

    assert token == "access_via_sibling"
    assert "sibling_token" in seen
    assert grant.load_count == 0, "Adopting must not re-run the grant"


async def test_invalid_grant_without_alternative_raises_rather_than_prompting(
    token_server,
) -> None:
    """With nothing left to try and an interactive grant, the client must
    surface the problem instead of silently opening a browser — which would
    also revoke every sibling process' client."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": "invalid_grant"}, status=400)

    endpoint = await token_server(handler)
    value = fakts_pointing_at(endpoint, refresh_token="dead_token")

    grant = StaticGrant(fakts=value, requires_user_interaction=True)
    fakts = Fakts(grant=grant, cache=MemoryCache(), manifest=make_manifest())

    async with fakts:
        with pytest.raises(NeedsReauthenticationError):
            await fakts.aget_token()

    assert grant.load_count == 1, "Only the initial load; no interactive re-run"


async def test_non_interactive_grant_reauthenticates_unattended(token_server) -> None:
    """Redeem-style grants carry no human cost, so they may re-run on their
    own. This is what keeps headless deployments alive past the refresh caps."""
    calls = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        calls["n"] += 1
        return web.json_response({"error": "invalid_grant"}, status=400)

    endpoint = await token_server(handler)
    dead = fakts_pointing_at(endpoint, refresh_token="dead_token")
    revived = fakts_pointing_at(endpoint, refresh_token="revived", access_token="revived_access")
    revived.auth.expires_at = time.time() + 3600

    class RevivingGrant(StaticGrant):
        async def aload(self) -> ActiveFakts:
            self.load_count += 1
            return dead if self.load_count == 1 else revived

    grant = RevivingGrant(fakts=dead, requires_user_interaction=False)
    fakts = Fakts(grant=grant, cache=MemoryCache(), manifest=make_manifest())

    async with fakts:
        token = await fakts.aget_token()

    assert token == "revived_access"
    assert grant.load_count == 2


# --------------------------------------------------------------------------- #
# Local expiry classification
# --------------------------------------------------------------------------- #


async def test_idle_refresh_token_fails_without_a_round_trip(token_server) -> None:
    """An obviously-dead credential should not be spent on a doomed request,
    and the error should say what actually happened."""
    calls = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        calls["n"] += 1
        return web.json_response(token_body("x", "y"))

    endpoint = await token_server(handler)
    value = fakts_pointing_at(endpoint)
    value.auth.refresh_issued_at = time.time() - REFRESH_TOKEN_MAX_AGE - 60

    fakts = Fakts(
        grant=StaticGrant(fakts=value), cache=MemoryCache(), manifest=make_manifest()
    )

    async with fakts:
        with pytest.raises(NeedsReauthenticationError, match="unused for too long"):
            await fakts.aget_token()

    assert calls["n"] == 0


async def test_expired_refresh_chain_is_named_as_such(token_server) -> None:
    """Rotating does not reset the chain cap, so even a permanently running
    app eventually needs a human — and should be told so plainly."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response(token_body("x", "y"))

    endpoint = await token_server(handler)
    value = fakts_pointing_at(endpoint)
    value.auth.chain_started_at = time.time() - REFRESH_CHAIN_MAX_AGE - 60

    fakts = Fakts(
        grant=StaticGrant(fakts=value), cache=MemoryCache(), manifest=make_manifest()
    )

    async with fakts:
        with pytest.raises(NeedsReauthenticationError, match="maximum age"):
            await fakts.aget_token()


# --------------------------------------------------------------------------- #
# arefresh_token: the transport 401 path
# --------------------------------------------------------------------------- #


async def test_refresh_token_never_prompts(token_server) -> None:
    """A 401 inside an unrelated request must never open a browser."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": "invalid_grant"}, status=400)

    endpoint = await token_server(handler)
    value = fakts_pointing_at(endpoint, refresh_token="dead")

    grant = StaticGrant(fakts=value, requires_user_interaction=True)
    fakts = Fakts(
        grant=grant,
        cache=MemoryCache(),
        manifest=make_manifest(),
        reauth_policy=ReauthPolicy.ALWAYS,
    )

    async with fakts:
        with pytest.raises(NeedsReauthenticationError):
            await fakts.arefresh_token()

    assert grant.load_count == 1, (
        "arefresh_token is non-interactive by contract, even under ALWAYS"
    )


async def test_stale_token_cas_collapses_repeated_401s(token_server) -> None:
    """Transports retry a rejected operation several times. Each retry that
    reached the token endpoint would rotate again, spending credentials to
    fix something the first renewal already fixed."""
    calls = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        calls["n"] += 1
        return web.json_response(token_body(f"access_{calls['n']}", f"rot_{calls['n']}"))

    endpoint = await token_server(handler)
    value = fakts_pointing_at(endpoint, refresh_token="original")

    fakts = Fakts(
        grant=StaticGrant(fakts=value), cache=MemoryCache(), manifest=make_manifest()
    )

    async with fakts:
        first = await fakts.arefresh_token(stale_token="whatever_failed")
        # A second retry reporting the *same* stale token gets the token we
        # already obtained, without another rotation.
        second = await fakts.arefresh_token(stale_token="whatever_failed")

    assert first == second == "access_1"
    assert calls["n"] == 1, f"expected exactly one rotation, got {calls['n']}"


# --------------------------------------------------------------------------- #
# The lost update
# --------------------------------------------------------------------------- #


async def test_alias_persist_cannot_clobber_a_rotated_credential(
    token_server, monkeypatch
) -> None:
    """The sharpest failure mode, and it needs no refresh contention at all:
    a process that never refreshed persists the preferred alias order — and
    with it the whole ActiveFakts, including the stale credential it happens
    to be holding — over a sibling's freshly rotated token."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response(token_body("x", "y"))

    endpoint = await token_server(handler)

    async def fake_challenge(self, alias, challenge_key=None) -> bool:
        if alias.id == "primary":
            raise Exception("unreachable")
        return True

    monkeypatch.setattr(Fakts, "achallenge_alias", fake_challenge)

    ours = fakts_pointing_at(endpoint, refresh_token="old_token")
    ours.auth.refresh_issued_at = time.time() - 100

    sibling = fakts_pointing_at(endpoint, refresh_token="freshly_rotated")
    sibling.auth.refresh_issued_at = time.time()

    cache = MemoryCache(value=sibling)
    fakts = Fakts(
        grant=StaticGrant(fakts=ours), cache=cache, manifest=make_manifest()
    )

    async with fakts:
        fakts.loaded_fakts = ours
        await fakts.aget_alias("test", omit_report=True)

    assert cache.value is not None
    assert cache.value.auth.refresh_token == "freshly_rotated", (
        "Persisting the alias order must not roll the credential back"
    )


async def test_report_cannot_wipe_resolved_aliases(token_server, monkeypatch) -> None:
    """Regression: taking the report token used to be able to adopt a cached
    credential mid-resolution, clearing the alias map that had just been
    published and turning a successful resolution into AliasNotFoundError."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response(token_body("reporting_access", "rot"))

    endpoint = await token_server(handler)

    async def fake_challenge(self, alias, challenge_key=None) -> bool:
        return True

    monkeypatch.setattr(Fakts, "achallenge_alias", fake_challenge)

    ours = fakts_pointing_at(endpoint, refresh_token="ours")
    sibling = fakts_pointing_at(endpoint, refresh_token="sibling_rotated")

    fakts = Fakts(
        grant=StaticGrant(fakts=ours),
        cache=MemoryCache(value=sibling),
        manifest=make_manifest(),
    )

    async with fakts:
        # report_endpoint points nowhere, so the report itself fails and is
        # swallowed — what matters is that resolution still succeeds.
        alias = await fakts.aget_alias("test")

    assert alias.id == "primary"


# --------------------------------------------------------------------------- #
# Token lifetime arithmetic
# --------------------------------------------------------------------------- #


async def test_expiry_absent_means_opaque() -> None:
    assert resolve_expiry(None, skew=30) is None


async def test_expiry_long_lifetime_subtracts_full_skew() -> None:
    now = 1_000_000.0
    assert resolve_expiry(3600, skew=30, now=now) == now + 3570


async def test_expiry_short_lifetime_clamps_the_skew() -> None:
    """A genuinely short token must be neither eternal nor instantly stale:
    treating it as eternal means never refreshing until a 401, and treating
    it as expired makes every single get a round trip."""
    now = 1_000_000.0
    result = resolve_expiry(20, skew=30, now=now)
    assert result is not None
    assert now < result < now + 20
    assert result == now + 10


async def test_expiry_non_positive_is_already_expired() -> None:
    now = 1_000_000.0
    assert resolve_expiry(0, skew=30, now=now) == now


# --------------------------------------------------------------------------- #
# Cache hygiene
# --------------------------------------------------------------------------- #


async def test_cache_file_is_private(tmp_path: Path) -> None:
    """The cache now holds a live rotating secret."""
    cache_file = tmp_path / "cache.json"
    cache = FileCache(cache_file=str(cache_file))

    await cache.aset(make_fakts_value())

    mode = os.stat(cache_file).st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


async def test_cache_write_leaves_no_temp_file(tmp_path: Path) -> None:
    """A stray temp file would leave the refresh token readable."""
    cache_file = tmp_path / "cache.json"
    cache = FileCache(cache_file=str(cache_file))

    await cache.aset(make_fakts_value())

    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


async def test_v1_cache_file_is_a_miss_not_a_crash(tmp_path: Path) -> None:
    """Every protocol-v1 cache fails validation on the now-required fields;
    that must read as "nothing cached", not as a startup failure."""
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        '{"fakts": {"self": {"deployment_name": "d", "alias": {"id": "a", "host": "h"}},'
        ' "auth": {"client_token": "t", "client_id": "c", "client_secret": "s",'
        ' "token_url": "http://x/token", "report_url": "http://x/report"},'
        ' "instances": {}, "statuses": {}}, "created": "2026-01-01T00:00:00", "hash": ""}'
    )

    cache = FileCache(cache_file=str(cache_file))
    assert await cache.aload() is None


async def test_cache_write_failure_is_not_fatal(token_server) -> None:
    """Losing the write is bad, but failing the call would be worse: we hold
    a good access token and retrying only burns another rotation."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response(token_body("good_access", "rotated"))

    endpoint = await token_server(handler)
    value = fakts_pointing_at(endpoint, refresh_token="original")

    class FailingCache(BaseModel):
        value: Optional[ActiveFakts] = None
        hash: str = ""

        async def aload(self) -> Optional[ActiveFakts]:
            return self.value

        async def aset(self, value: ActiveFakts) -> None:
            raise OSError("read-only file system")

        async def areset(self) -> None:
            return None

    fakts = Fakts(
        grant=StaticGrant(fakts=value), cache=FailingCache(), manifest=make_manifest()
    )

    async with fakts:
        assert await fakts.aget_token() == "good_access"


# --------------------------------------------------------------------------- #
# Servers that declare no token lifetime
# --------------------------------------------------------------------------- #


async def test_no_expires_in_token_is_opaque_and_reused(token_server) -> None:
    """Without expires_in the token has no known lifetime, so it is treated
    as opaque: reused rather than renewed on a timer."""
    calls = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        calls["n"] += 1
        body = token_body(f"access_{calls['n']}", f"rot_{calls['n']}")
        del body["expires_in"]
        return web.json_response(body)

    endpoint = await token_server(handler)
    value = fakts_pointing_at(endpoint, refresh_token="original")

    fakts = Fakts(
        grant=StaticGrant(fakts=value), cache=MemoryCache(), manifest=make_manifest()
    )

    async with fakts:
        first = await fakts.aget_token()
        second = await fakts.aget_token()

    assert first == second == "access_1"
    assert calls["n"] == 1, "An opaque token must not be renewed speculatively"


async def test_opaque_token_can_still_be_renewed_after_rejection(token_server) -> None:
    """Since no timer will ever renew an opaque token, rejection is the only
    recovery — so it must actually get through to a renewal."""
    calls = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        calls["n"] += 1
        body = token_body(f"access_{calls['n']}", f"rot_{calls['n']}")
        del body["expires_in"]
        return web.json_response(body)

    endpoint = await token_server(handler)
    value = fakts_pointing_at(endpoint, refresh_token="original")

    fakts = Fakts(
        grant=StaticGrant(fakts=value), cache=MemoryCache(), manifest=make_manifest()
    )

    async with fakts:
        first = await fakts.aget_token()
        # The transport reports back exactly the token that was rejected.
        renewed = await fakts.arefresh_token(stale_token=first)

    assert first == "access_1"
    assert renewed == "access_2", "A rejected opaque token must reach a renewal"
    assert calls["n"] == 2


async def test_alias_order_persists_when_credential_is_unchanged(
    token_server, monkeypatch
) -> None:
    """The lost-update guard must not cost us the alias-preference
    optimization in the ordinary single-process case."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response(token_body("x", "y"))

    endpoint = await token_server(handler)

    async def fake_challenge(self, alias, challenge_key=None) -> bool:
        if alias.id == "primary":
            raise Exception("unreachable")
        return True

    monkeypatch.setattr(Fakts, "achallenge_alias", fake_challenge)

    value = fakts_pointing_at(endpoint, refresh_token="same_token")
    cache = MemoryCache(value=value)
    fakts = Fakts(
        grant=StaticGrant(fakts=value), cache=cache, manifest=make_manifest()
    )

    async with fakts:
        alias = await fakts.aget_alias("test", omit_report=True)

    assert alias.id == "fallback"
    assert cache.value is not None
    assert cache.value.instances["test"].aliases[0].id == "fallback", (
        "The working alias must still be persisted as the preferred one"
    )
