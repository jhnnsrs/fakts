"""Tests for ``fakts_next.testing`` — the hot-pluggable TestingFakts.

No docker, no network: TestingFakts overrides only the alias-challenge and
token-renewal seams, so everything else here (context publication, alias
resolution, token caching/expiry/refresh semantics) runs the real Fakts
machinery.
"""

import pytest

from fakts_next import Alias, NoFaktsFound, get_current_fakts_next
from fakts_next.testing import build_testing_fakts


@pytest.mark.asyncio
async def test_hotplugs_into_current_context_and_resets_on_exit():
    fakts = build_testing_fakts(aliases={"alpaka": "http://testserver"})
    async with fakts:
        assert get_current_fakts_next() is fakts
    with pytest.raises(NoFaktsFound):
        get_current_fakts_next()


@pytest.mark.asyncio
async def test_alias_resolves_without_omit_kwargs():
    """The consumer-shaped call: no ``omit_challenge``/``omit_report`` —
    the overridden challenge always passes."""
    async with build_testing_fakts(aliases={"alpaka": "http://testserver"}) as fakts:
        alias = await fakts.aget_alias("alpaka")
        assert alias.to_http_path("/llm/v1") == "http://testserver/llm/v1"


@pytest.mark.asyncio
async def test_alias_accepts_url_forms_and_alias_models():
    async with build_testing_fakts(
        aliases={
            "secure": "https://api.example.com:8443/alpaka",
            "explicit": Alias(id="explicit", host="h", port=1),
        }
    ) as fakts:
        secure = await fakts.aget_alias("secure")
        assert secure.ssl and secure.port == 8443 and secure.path == "alpaka"
        explicit = await fakts.aget_alias("explicit")
        assert explicit.host == "h" and explicit.port == 1


@pytest.mark.asyncio
async def test_static_token_is_fetched_once_and_cached():
    async with build_testing_fakts(aliases={}, token="tok") as fakts:
        assert await fakts.aget_token() == "tok"
        assert await fakts.aget_token() == "tok"
        assert fakts.token_fetches == 1


@pytest.mark.asyncio
async def test_zero_lifetime_rotates_every_call_and_last_token_repeats():
    async with build_testing_fakts(
        aliases={}, tokens=["a", "b"], token_lifetime=0
    ) as fakts:
        assert await fakts.aget_token() == "a"
        assert await fakts.aget_token() == "b"
        assert await fakts.aget_token() == "b"
        assert fakts.token_fetches == 3


@pytest.mark.asyncio
async def test_refresh_token_rotates_with_stale_token_semantics():
    async with build_testing_fakts(aliases={}, tokens=["a", "b", "c"]) as fakts:
        first = await fakts.aget_token()
        assert first == "a"
        assert await fakts.arefresh_token(stale_token=first) == "b"
        # A retry still holding the replaced token gets the current one back
        # instead of burning another rotation — the real idempotency contract.
        assert await fakts.arefresh_token(stale_token=first) == "b"
        assert fakts.token_fetches == 2


@pytest.mark.asyncio
async def test_first_alias_resolution_spends_the_first_fetch():
    """Real behavior worth pinning: alias refresh takes a report token up
    front, so the first ``aget_alias`` performs the first token fetch."""
    async with build_testing_fakts(aliases={"svc": "http://x"}, tokens=["a", "b"]) as fakts:
        assert fakts.token_fetches == 0
        await fakts.aget_alias("svc")
        assert fakts.token_fetches == 1
        assert await fakts.aget_token() == "a"


def test_sync_with_publishes_context_to_the_calling_thread():
    """The koil bridge re-applies contextvars set in the loop thread, so a
    plain ``with`` hot-plugs for synchronous consumers too."""
    fakts = build_testing_fakts(aliases={"alpaka": "http://testserver"})
    with fakts:
        assert get_current_fakts_next() is fakts
        assert (
            fakts.get_alias("alpaka").to_http_path("/llm/v1")
            == "http://testserver/llm/v1"
        )
        assert fakts.get_token() == "test-token"


def test_rejects_unparseable_alias_urls():
    with pytest.raises(ValueError, match="scheme and"):
        build_testing_fakts(aliases={"svc": "not-a-url"})
