"""How the aliases of a service are challenged: the last known good one first
and alone, the others alongside it once it is slow, and a service that is down
on its own rather than with every other one."""

import asyncio
from collections import defaultdict
from typing import Any

import pytest

from fakts import Fakts
from fakts.errors import AttemptOutcome, CompositionError, ServiceUnreachableError
from fakts.fakts import Fakts as FaktsClass
from fakts.models import Alias, Instance, Manifest, Requirement

from .helpers import CountingGrant, MemoryCache, make_fakts_value, make_manifest

pytestmark = pytest.mark.asyncio


class Gated:
    """A challenger whose aliases answer when the test lets them.

    ``answers`` maps an alias id to what its challenge gives (True by default;
    an exception is raised). An alias answers at once unless it is ``held``.
    """

    def __init__(self, **answers: Any) -> None:
        self.answers = answers
        self.calls: list[str] = []
        self.held: set[str] = set()
        self._gates: defaultdict[str, asyncio.Event] = defaultdict(asyncio.Event)

    def hold(self, *aliases: str) -> "Gated":
        self.held |= set(aliases)
        return self

    def release(self, *aliases: str) -> None:
        self.held -= set(aliases)
        for alias in aliases:
            self._gates[alias].set()

    def install(self, monkeypatch: pytest.MonkeyPatch) -> "Gated":
        async def challenge(
            _fakts: FaktsClass, alias: Alias, challenge_key: object = None, proxy: Any = None
        ) -> bool:
            self.calls.append(alias.id)
            if alias.id in self.held:
                await self._gates[alias.id].wait()
            answer = self.answers.get(alias.id, True)
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(FaktsClass, "_achallenge_alias", challenge)
        return self


def two_services() -> tuple[Any, Manifest]:
    """``up`` (one alias) and the optional ``down`` (one alias)."""
    value = make_fakts_value()
    value.auth.report_endpoint = None
    value.instances = {
        key: Instance(
            service=f"{key}_service",
            identifier=f"{key}_instance",
            aliases=[Alias(id=key, host="localhost", port=8000, path=f"/{key}")],
        )
        for key in ("up", "down")
    }
    manifest = Manifest(
        version="0.1.0",
        identifier="test_manifest",
        scopes=["openid"],
        requirements=[
            Requirement(key="up", service="up_service"),
            Requirement(key="down", service="down_service", optional=True),
        ],
    )
    return value, manifest


# --- the race ---------------------------------------------------------------


async def test_an_alias_that_answers_at_once_is_the_only_one_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gated = Gated().install(monkeypatch)
    fakts = Fakts(grant=CountingGrant(fakts=make_fakts_value()), manifest=make_manifest())
    async with fakts:
        alias = await fakts.aget_alias("test", omit_report=True)
    assert alias.id == "primary"
    assert gated.calls == ["primary"]


async def test_a_slow_first_alias_is_joined_by_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first alias never answers: after the head start the next one is
    asked too, and used. Nobody waits out the first one's timeout."""
    gated = Gated().hold("primary").install(monkeypatch)
    fakts = Fakts(
        grant=CountingGrant(fakts=make_fakts_value()),
        manifest=make_manifest(),
        alias_head_start=0.01,
        alias_challenge_timeout=30,
    )
    async with fakts:
        alias = await asyncio.wait_for(fakts.aget_alias("test", omit_report=True), 5)
    assert alias.id == "fallback"
    assert gated.calls == ["primary", "fallback"]


async def test_a_first_alias_that_fails_is_not_waited_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """The head start is for an answer, not a pause: a refusal ends it."""
    Gated(primary=OSError("connection refused")).install(monkeypatch)
    fakts = Fakts(
        grant=CountingGrant(fakts=make_fakts_value()),
        manifest=make_manifest(),
        alias_head_start=30,
    )
    async with fakts:
        alias = await asyncio.wait_for(fakts.aget_alias("test", omit_report=True), 5)
    assert alias.id == "fallback"


async def test_the_first_alias_wins_while_it_answers_in_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two working aliases do not swap places: the others are not even asked
    until the head start is over, and then the first to answer is used."""
    gated = Gated().hold("primary").install(monkeypatch)
    fakts = Fakts(
        grant=CountingGrant(fakts=make_fakts_value()),
        manifest=make_manifest(),
        alias_head_start=30,
    )
    async with fakts:
        lookup = asyncio.ensure_future(fakts.aget_alias("test", omit_report=True))
        while "primary" not in gated.calls:
            await asyncio.sleep(0)
        gated.release("primary")
        alias = await asyncio.wait_for(lookup, 5)
    assert alias.id == "primary"
    assert gated.calls == ["primary"]


async def test_aliases_that_do_not_answer_cost_one_timeout_between_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = make_fakts_value()
    value.instances["test"].aliases.append(
        Alias(id="third", host="localhost", port=8002, path="/test")
    )
    Gated().hold("primary", "fallback", "third").install(monkeypatch)
    fakts = Fakts(
        grant=CountingGrant(fakts=value),
        manifest=make_manifest(),
        alias_head_start=0.01,
        alias_challenge_timeout=0.2,
    )
    async with fakts:
        started = asyncio.get_running_loop().time()
        with pytest.raises(CompositionError) as raised:
            await fakts.aget_alias("test", omit_report=True)
        took = asyncio.get_running_loop().time() - started
    # One after another this was three timeouts (0.6 s).
    assert took < 0.4, took
    (failure,) = raised.value.failures
    assert [a.outcome for a in failure.attempts] == [AttemptOutcome.TIMEOUT] * 3


# --- a service that is down ---------------------------------------------------


async def test_a_service_that_is_down_is_not_asked_again_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = OSError("connection refused")
    gated = Gated(primary=refused, fallback=refused).install(monkeypatch)
    fakts = Fakts(
        grant=CountingGrant(fakts=make_fakts_value()),
        manifest=make_manifest(),
        alias_retry_after=30,
    )
    async with fakts:
        with pytest.raises(CompositionError) as first:
            await fakts.aget_alias("test", omit_report=True)
        asked = len(gated.calls)
        with pytest.raises(CompositionError) as second:
            await fakts.aget_alias("test", omit_report=True)
        assert len(gated.calls) == asked, "a service just found down was challenged again"
        assert second.value.failures == first.value.failures

        # Asking for it is asking.
        with pytest.raises(CompositionError):
            await fakts.aget_alias("test", omit_report=True, force_refresh=True)
        assert len(gated.calls) == 2 * asked

        gated.answers.clear()
        assert (await fakts.aget_alias("test", omit_report=True, force_refresh=True)).id


async def test_only_the_service_that_was_down_is_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, manifest = two_services()
    gated = Gated(down=OSError("connection refused")).install(monkeypatch)
    fakts = Fakts(grant=CountingGrant(fakts=value), manifest=manifest, alias_retry_after=0)
    async with fakts:
        assert (await fakts.aget_alias("up", omit_report=True)).id == "up"
        for _ in range(3):
            with pytest.raises(ServiceUnreachableError) as raised:
                await fakts.aget_alias("down", omit_report=True)
            assert raised.value.failure.key == "down"
            assert await fakts.aget_alias_or_none("down", omit_report=True) is None
        assert gated.calls.count("up") == 1, "a healthy service was challenged again"
        assert gated.calls.count("down") == 7

        gated.answers.clear()
        assert (await fakts.aget_alias("down", omit_report=True)).id == "down"
        assert gated.calls.count("up") == 1
        assert fakts.report_map["down"].valid


async def test_a_resolved_service_is_served_while_another_is_being_challenged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lookup of a service that is down waits for its challenge (seconds);
    that used to hold the alias lock, and every other lookup with it."""
    value, manifest = two_services()
    gated = Gated(down=OSError("connection refused")).install(monkeypatch)
    fakts = Fakts(grant=CountingGrant(fakts=value), manifest=manifest, alias_retry_after=0)
    async with fakts:
        await fakts.aget_alias("up", omit_report=True)
        gated.hold("down")
        asked = len(gated.calls)
        waiting = asyncio.ensure_future(fakts.aget_alias_or_none("down", omit_report=True))
        while len(gated.calls) == asked:
            await asyncio.sleep(0)
        assert (await asyncio.wait_for(fakts.aget_alias("up", omit_report=True), 1)).id == "up"
        gated.release("down")
        assert await waiting is None


async def test_a_reload_that_changes_nothing_challenges_nothing_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The self-heal reloads a cached configuration that failed. If the grant
    hands back the same aliases, they are down, not stale: no second round."""
    refused = OSError("connection refused")
    gated = Gated(primary=refused, fallback=refused).install(monkeypatch)
    grant = CountingGrant(fakts=make_fakts_value(), requires_user_interaction=False)
    cache = MemoryCache(value=make_fakts_value(), hash="static")
    fakts = Fakts(grant=grant, cache=cache, manifest=make_manifest())
    async with fakts:
        with pytest.raises(CompositionError):
            await fakts.aget_alias("test", omit_report=True)
    assert grant.load_count == 1, "the stale cache should have been reloaded once"
    assert sorted(gated.calls) == ["fallback", "primary"]
