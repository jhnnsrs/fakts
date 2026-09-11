"""Unit tests for the pure-logic utilities (``utils.py``) and the context
helpers (``helpers.py``)."""

import pytest

from fakts_next import Fakts
from fakts_next.errors import NoFaktsFound
from fakts_next.fakts import Fakts as FaktsClass
from fakts_next.grants.hard import HardFaktsGrant
from fakts_next.helpers import afakt, fakt
from fakts_next.models import Alias
from fakts_next.utils import truncate, update_nested

from .test_fakts_behavior import make_fakts_value, make_manifest


# --------------------------------------------------------------------------- #
# utils.truncate
# --------------------------------------------------------------------------- #


def test_truncate_under_limit_passthrough():
    assert truncate("hello", max_length=300) == "hello"


def test_truncate_strips_whitespace():
    assert truncate("   hello   ") == "hello"


def test_truncate_empty_string():
    assert truncate("   ") == ""


def test_truncate_over_limit_adds_note():
    text = "a" * 350
    result = truncate(text, max_length=300)
    assert result.startswith("a" * 300)
    assert "50 more characters truncated" in result


# --------------------------------------------------------------------------- #
# utils.update_nested
# --------------------------------------------------------------------------- #


def test_update_nested_shallow():
    d = {"a": 1, "b": 2}
    update_nested(d, {"b": 3})
    assert d == {"a": 1, "b": 3}


def test_update_nested_recursive_merge():
    d = {"a": {"x": 1, "y": 2}}
    update_nested(d, {"a": {"y": 3, "z": 4}})
    assert d == {"a": {"x": 1, "y": 3, "z": 4}}


def test_update_nested_is_inplace_and_returns_same_object():
    d = {"a": 1}
    result = update_nested(d, {"b": 2})
    assert result is d
    assert d == {"a": 1, "b": 2}


# --------------------------------------------------------------------------- #
# helpers.afakt / helpers.fakt
# --------------------------------------------------------------------------- #


def _hard_fakts(monkeypatch: pytest.MonkeyPatch) -> Fakts:
    async def fake_challenge(
        self: FaktsClass, alias: Alias, challenge_key: object = None
    ) -> bool:
        return True

    monkeypatch.setattr(FaktsClass, "achallenge_alias", fake_challenge)
    grant = HardFaktsGrant(fakts=make_fakts_value())
    return Fakts(grant=grant, manifest=make_manifest())


@pytest.mark.asyncio
async def test_afakt_returns_alias_from_current_context(
    monkeypatch: pytest.MonkeyPatch,
):
    async with _hard_fakts(monkeypatch):
        alias = await afakt("test", omit_challenge=True)
    assert isinstance(alias, Alias)
    assert alias.id == "primary"


def test_fakt_sync_wrapper_returns_alias(monkeypatch: pytest.MonkeyPatch):
    with _hard_fakts(monkeypatch):
        alias = fakt("test", omit_challenge=True)
    assert isinstance(alias, Alias)
    assert alias.id == "primary"


@pytest.mark.asyncio
async def test_afakt_outside_context_raises():
    with pytest.raises(NoFaktsFound):
        await afakt("test", omit_challenge=True)
