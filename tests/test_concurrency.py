"""Tests for the races that only appear when two things happen at once.

The rest of the suite drives the client one call at a time, which is exactly
the shape that hides these: every bug here passed a green suite. Each test
below fails on the pre-fix code for a *specific* reason, noted in its
docstring — a concurrency test that would pass either way is worse than none,
because it looks like coverage.
"""

import asyncio
import os
import time
from typing import AsyncIterator, Awaitable, Callable, Optional

import pytest
import pytest_asyncio
from aiohttp import web
from pydantic import BaseModel

from fakts import Fakts
from fakts.cache.file import FileCache
from fakts.errors import NeedsReauthenticationError, NotEnteredError
from fakts.models import ActiveFakts

from .test_fakts_behavior import make_fakts_value, make_manifest
from .test_token_path import (
    MemoryCache,
    StaticGrant,
    fakts_pointing_at,
    token_body,
)

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


class SlowGrant(BaseModel):
    """A grant that yields to the loop while loading, so a second task can
    interleave with it the way a real device-code flow would."""

    fakts: ActiveFakts
    load_count: int = 0
    delay: float = 0.05
    requires_user_interaction: bool = True

    async def aload(self) -> ActiveFakts:
        self.load_count += 1
        await asyncio.sleep(self.delay)
        return self.fakts


async def _always_pass(self, alias, challenge_key=None) -> bool:
    return True


# --------------------------------------------------------------------------- #
# Alias invalidation after the credential changes
# --------------------------------------------------------------------------- #


async def test_refresh_that_drops_an_instance_reresolves_aliases(
    token_server, monkeypatch
) -> None:
    """A re-approval that *reduces* the grant must not leave us talking to a
    service we no longer have access to.

    Pre-fix, `_acommit_token_response` cleared `_aliases_refreshed` but
    `aget_alias` checked `alias_map` first, so the flag never took effect for
    a key that had already resolved — i.e. for every key that mattered.
    """
    body = token_body("access_2", "refresh_2")
    # The renewed session grants a different alias set for the same service.
    body["instances"]["test"]["aliases"] = [
        {"id": "relocated", "host": "localhost", "port": 9000, "path": "/test"}
    ]

    async def handler(request: web.Request) -> web.Response:
        return web.json_response(body)

    endpoint = await token_server(handler)
    monkeypatch.setattr(Fakts, "achallenge_alias", _always_pass)

    value = fakts_pointing_at(endpoint, access_token="access_1", expires_at=time.time() + 3600)
    fakts = Fakts(
        grant=StaticGrant(fakts=value),
        cache=MemoryCache(),
        manifest=make_manifest(),
    )

    async with fakts:
        first = await fakts.aget_alias("test", omit_report=True)
        assert first.id == "primary"

        await fakts.arefresh_token()

        second = await fakts.aget_alias("test", omit_report=True)
        assert second.id == "relocated", (
            "The refresh replaced this service's aliases; serving the one "
            "resolved against the previous grant is exactly the stale-access "
            "case instances_changed exists to catch"
        )


async def test_adopting_a_sibling_credential_reresolves_aliases(
    token_server, monkeypatch
) -> None:
    """Adoption replaces the whole ActiveFakts, instances included.

    Pre-fix, `_aadopt_cached_credentials` never touched the alias state at
    all — and under multi-process load adoption is the *common* path, so
    fixing only the commit path would have missed it every time.
    """

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": "invalid_grant"}, status=400)

    endpoint = await token_server(handler)
    monkeypatch.setattr(Fakts, "achallenge_alias", _always_pass)

    ours = fakts_pointing_at(endpoint, refresh_token="ours")

    # What a sibling process rotated to, with a different alias for the
    # same service and an access token that is still good.
    sibling = fakts_pointing_at(
        endpoint,
        refresh_token="siblings",
        access_token="siblings_access",
        expires_at=time.time() + 3600,
    )
    sibling.instances["test"].aliases = [
        make_fakts_value().instances["test"].aliases[1]  # only "fallback"
    ]

    cache = MemoryCache()
    fakts = Fakts(
        grant=StaticGrant(fakts=ours),
        cache=cache,
        manifest=make_manifest(),
    )

    async with fakts:
        first = await fakts.aget_alias("test", omit_report=True)
        assert first.id == "primary"

        # The sibling's rotation lands in the cache; our next renewal adopts it.
        cache.value = sibling
        await fakts.arefresh_token()

        second = await fakts.aget_alias("test", omit_report=True)
        assert second.id == "fallback", (
            "Adopting a credential whose instances differ must re-resolve"
        )


# --------------------------------------------------------------------------- #
# The stale-snapshot race in the token path
# --------------------------------------------------------------------------- #


async def test_concurrent_reload_does_not_force_a_spurious_reauth(
    token_server, monkeypatch
) -> None:
    """A benign `arefresh()` running alongside a 401 must not turn into a
    demand for re-authentication.

    Pre-fix, `_afetch_token` captured `loaded_fakts` once and never re-read
    it. The reload replaced it while the token task was blocked on
    `_load_lock`, so the token task went on to POST a refresh token the
    server had already revoked — and `_aadopt_cached_credentials` could not
    rescue it, because the cache now matched `loaded_fakts` and it correctly
    reported "nothing new". Every round failed and it raised.
    """
    posted: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        form = await request.post()
        refresh = str(form.get("refresh_token"))
        posted.append(refresh)
        if refresh != "current":
            # The revoked predecessor — exactly what a stale snapshot sends.
            return web.json_response({"error": "invalid_grant"}, status=400)
        return web.json_response(token_body("access_new", "rotated"))

    endpoint = await token_server(handler)
    monkeypatch.setattr(Fakts, "achallenge_alias", _always_pass)

    stale = fakts_pointing_at(endpoint, refresh_token="superseded")
    fresh = fakts_pointing_at(endpoint, refresh_token="current")

    grant = SlowGrant(fakts=fresh)
    fakts = Fakts(grant=grant, cache=MemoryCache(), manifest=make_manifest())

    async with fakts:
        # Start out holding the credential the reload is about to supersede.
        fakts.loaded_fakts = stale

        reload_task = asyncio.create_task(fakts.arefresh())
        await asyncio.sleep(0)  # let the reload take _load_lock first
        token_task = asyncio.create_task(fakts.arefresh_token())

        results = await asyncio.gather(reload_task, token_task)

    assert isinstance(results[1], str) and results[1]
    assert "superseded" not in posted, (
        "The renewal used the credential the concurrent reload had already "
        f"replaced. Posted: {posted}"
    )


# --------------------------------------------------------------------------- #
# Alias state under concurrent writers
# --------------------------------------------------------------------------- #


async def test_concurrent_alias_refresh_and_lookup_are_serialized(
    monkeypatch,
) -> None:
    """`arefresh_aliases` is public and used to take no lock at all, while
    `aget_alias` read the same state under `_alias_lock`.

    The sharp edge was `instance.aliases.sort()` mutating in place the very
    list `_aresolve_requirement` iterates. This drives both at once with a
    challenge that yields on every call, so the two interleave.
    """
    in_flight = 0
    overlaps = 0

    async def yielding_challenge(self, alias, challenge_key=None) -> bool:
        nonlocal in_flight, overlaps
        in_flight += 1
        if in_flight > 1:
            overlaps += 1
        await asyncio.sleep(0)
        in_flight -= 1
        return alias.id == "fallback"

    monkeypatch.setattr(Fakts, "achallenge_alias", yielding_challenge)

    fakts = Fakts(
        grant=StaticGrant(fakts=make_fakts_value()),
        cache=MemoryCache(),
        manifest=make_manifest(),
    )

    async with fakts:
        results = await asyncio.gather(
            fakts.arefresh_aliases(omit_report=True),
            fakts.aget_alias("test", omit_report=True),
            fakts.arefresh_aliases(omit_report=True),
            fakts.aget_alias("test", omit_report=True),
        )

        assert overlaps == 0, (
            "Two alias resolutions ran concurrently; one sorts each instance's "
            "alias list in place while the other iterates it"
        )
        for alias in (results[1], results[3]):
            assert alias.id == "fallback"
        assert fakts.alias_map["test"].id == "fallback"


# --------------------------------------------------------------------------- #
# Lost updates on the cache
# --------------------------------------------------------------------------- #


async def test_untimed_credential_cannot_clobber_a_rotated_one(
    token_server, monkeypatch
) -> None:
    """`test_alias_persist_cannot_clobber_a_rotated_credential` stamps
    `refresh_issued_at` on both sides, so it never exercises the branch that
    actually fires in production.

    Only `merge_token_response` ever sets that field, so *every* credential
    straight from a grant carries `None` — and `_is_stale_auth` used to read
    `None` as "safe to write", switching the guard off in precisely the case
    it was written for.
    """

    async def handler(request: web.Request) -> web.Response:
        return web.json_response(token_body("x", "y"))

    endpoint = await token_server(handler)

    async def fake_challenge(self, alias, challenge_key=None) -> bool:
        if alias.id == "primary":
            raise Exception("unreachable")
        return True

    monkeypatch.setattr(Fakts, "achallenge_alias", fake_challenge)

    # Straight from a grant: no issue time, as is normal.
    ours = fakts_pointing_at(endpoint, refresh_token="old_token")
    ours.auth.refresh_issued_at = None

    sibling = fakts_pointing_at(endpoint, refresh_token="freshly_rotated")
    sibling.auth.refresh_issued_at = time.time()

    cache = MemoryCache(value=sibling)
    fakts = Fakts(
        grant=StaticGrant(fakts=ours), cache=cache, manifest=make_manifest()
    )

    async with fakts:
        fakts.loaded_fakts = ours
        # Resolving moves "fallback" to the front, which persists the whole
        # ActiveFakts — credential included.
        await fakts.aget_alias("test", omit_report=True)

    assert cache.value is not None
    assert cache.value.auth.refresh_token == "freshly_rotated", (
        "An untimed credential must not overwrite one that was demonstrably "
        "rotated; the token on disk would be revoked"
    )


async def test_file_cache_transaction_serializes_read_compare_write(
    tmp_path,
) -> None:
    """The compare and the write have to be one step across *processes*.

    `_load_lock` is an asyncio.Lock, so it orders nothing between siblings.
    This drives two FileCache instances on one path through the same
    interleaving a real pair of processes would hit.
    """
    path = str(tmp_path / "cache.json")
    first = FileCache(cache_file=path, hash="static")
    second = FileCache(cache_file=path, hash="static")

    order: list[str] = []

    async def writer(cache: FileCache, name: str, token: str) -> None:
        async with cache.atransaction():
            order.append(f"{name}:enter")
            await cache.aload()
            await asyncio.sleep(0.02)  # widen the window a lock must cover
            value = make_fakts_value(refresh_token=token)
            await cache.aset(value)
            order.append(f"{name}:exit")

    await asyncio.gather(
        writer(first, "a", "token_a"),
        writer(second, "b", "token_b"),
    )

    # Whoever went second wins, but neither may interleave with the other.
    assert order in (
        ["a:enter", "a:exit", "b:enter", "b:exit"],
        ["b:enter", "b:exit", "a:enter", "a:exit"],
    ), f"transactions interleaved: {order}"

    assert os.path.exists(path)


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


async def test_nested_enter_is_refused() -> None:
    """Re-entering installed three fresh locks over the ones the outer scope
    was relying on, so mutual exclusion was lost silently and the inner exit
    then nulled them out from under the outer body."""
    fakts = Fakts(
        grant=StaticGrant(fakts=make_fakts_value()),
        cache=MemoryCache(),
        manifest=make_manifest(),
    )

    async with fakts:
        outer_lock = fakts._load_lock
        with pytest.raises(NotEnteredError):
            async with fakts:
                pass
        assert fakts._load_lock is outer_lock, (
            "the refused re-entry must leave the outer scope's locks intact"
        )


# --------------------------------------------------------------------------- #
# Session lifecycle: alogin / alogout
# --------------------------------------------------------------------------- #


async def test_alogin_on_a_healthy_session_does_nothing(token_server) -> None:
    """`alogin()` is the recovery users are told to call, so it has to be
    safe to call unconditionally: no prompt, and above all no rotation.

    Rotating here would revoke the credential every sibling process shares,
    turning the documented recovery into the outage it exists to avoid.
    """
    hits: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        hits.append("token")
        return web.json_response(token_body("access_2", "refresh_2"))

    endpoint = await token_server(handler)

    value = fakts_pointing_at(
        endpoint, access_token="still_good", expires_at=time.time() + 3600
    )
    grant = StaticGrant(fakts=value)
    fakts = Fakts(grant=grant, cache=MemoryCache(), manifest=make_manifest())

    async with fakts:
        await fakts.aload()
        assert grant.load_count == 1

        await fakts.alogin()
        await fakts.alogin()

    assert hits == [], "a valid session must not be rotated by alogin()"
    assert grant.load_count == 1, "alogin() must not re-run the grant"


async def test_alogin_recovers_a_dead_session_in_one_call(token_server) -> None:
    """The README's worked example, as a test.

    The grant here *requires user interaction*, which is the whole point: an
    ordinary `aget_token()` refuses to prompt and raises, and only `alogin()`
    — which passes interactive=True — can revive the session. A test using a
    non-interactive grant would pass either way, since `_areauthenticate`
    re-runs those unattended regardless.
    """

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": "invalid_grant"}, status=400)

    endpoint = await token_server(handler)

    dead = fakts_pointing_at(endpoint, refresh_token="dead")
    alive = fakts_pointing_at(
        endpoint, access_token="fresh_access", expires_at=time.time() + 3600
    )
    grant = StaticGrant(fakts=alive, requires_user_interaction=True)

    fakts = Fakts(grant=grant, cache=MemoryCache(), manifest=make_manifest())

    async with fakts:
        fakts.loaded_fakts = dead
        with pytest.raises(NeedsReauthenticationError):
            await fakts.aget_token()

        fakts.loaded_fakts = dead
        result = await fakts.alogin()
        assert result.auth.access_token == "fresh_access"
        assert await fakts.aget_token() == "fresh_access"


async def test_alogout_forgets_the_session(tmp_path) -> None:
    """Logout clears both the cache and every scrap of in-memory state, so a
    later call re-runs the grant rather than resurrecting the old session."""
    cache_file = tmp_path / "cache.json"
    grant = SlowGrant(fakts=make_fakts_value(), delay=0)
    fakts = Fakts(
        grant=grant,
        cache=FileCache(cache_file=str(cache_file), hash="static"),
        manifest=make_manifest(),
    )

    async with fakts:
        await fakts.aload()
        assert cache_file.exists()
        assert grant.load_count == 1

        await fakts.alogout()

        assert not cache_file.exists(), "the cached session must be gone"
        assert fakts.loaded_fakts is None
        assert fakts.loaded_token is None
        assert fakts.alias_map == {}

        # ...and the next use starts over rather than reviving the old one.
        await fakts.aload()
        assert grant.load_count == 2


async def test_alogout_leaves_no_lock_file(tmp_path) -> None:
    """The advisory lock is an implementation detail of the cache; logging out
    must not leave one sitting next to a cache file it just deleted."""
    cache_file = tmp_path / "cache.json"
    fakts = Fakts(
        grant=StaticGrant(fakts=make_fakts_value()),
        cache=FileCache(cache_file=str(cache_file), hash="static"),
        manifest=make_manifest(),
    )

    async with fakts:
        await fakts.aload()
        await fakts.alogout()

    assert list(tmp_path.iterdir()) == [], f"litter left: {list(tmp_path.iterdir())}"


async def test_alogout_concurrent_with_alias_resolution_does_not_deadlock(
    monkeypatch,
) -> None:
    """alogout() is the only operation holding all three locks, so it is the
    one that deadlocks if it takes them out of L1 order.

    The contention has to be engineered, not hoped for. The challenge is
    gated so alias resolution is *inside* `_alias_lock` when logout starts,
    and it rejects the first alias so the resolution ends by reordering and
    persisting — which needs `_load_lock`. Take the locks load-first and the
    two tasks hold exactly what the other is waiting for.
    """
    challenging = asyncio.Event()
    proceed = asyncio.Event()

    async def gated_challenge(self, alias, challenge_key=None) -> bool:
        challenging.set()
        await proceed.wait()
        return alias.id == "fallback"

    monkeypatch.setattr(Fakts, "achallenge_alias", gated_challenge)

    value = make_fakts_value(access_token="tok", expires_at=time.time() + 3600)
    fakts = Fakts(
        grant=SlowGrant(fakts=value, delay=0),
        cache=MemoryCache(),
        manifest=make_manifest(),
    )

    async with fakts:
        await fakts.aload()

        alias_task = asyncio.create_task(fakts.aget_alias("test", omit_report=True))
        await asyncio.wait_for(challenging.wait(), timeout=2)

        logout_task = asyncio.create_task(fakts.alogout())
        await asyncio.sleep(0.05)  # let logout take whatever it is going to take
        proceed.set()

        results = await asyncio.wait_for(
            asyncio.gather(alias_task, logout_task, return_exceptions=True),
            timeout=5,
        )

    for r in results:
        assert not isinstance(r, (asyncio.TimeoutError, asyncio.CancelledError)), r


async def test_cache_reset_cannot_race_a_concurrent_persist(tmp_path) -> None:
    """`areset()` used to be a bare os.remove — the one cache mutation that
    skipped the transaction every other write goes through, which is exactly
    the sibling race the lock was added to close."""
    path = str(tmp_path / "cache.json")
    writer = FileCache(cache_file=path, hash="static")
    resetter = FileCache(cache_file=path, hash="static")

    order: list[str] = []

    async def persist() -> None:
        async with writer.atransaction():
            order.append("write:enter")
            await asyncio.sleep(0.02)
            await writer.aset(make_fakts_value(refresh_token="written"))
            order.append("write:exit")

    async def reset() -> None:
        await asyncio.sleep(0.005)  # start inside the writer's window
        order.append("reset:start")
        await resetter.areset()
        order.append("reset:done")

    await asyncio.gather(persist(), reset())

    assert order.index("write:exit") < order.index("reset:done"), (
        f"areset() tore into an in-flight write: {order}"
    )
