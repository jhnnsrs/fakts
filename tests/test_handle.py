"""Tests for what a service is handed: ``Require``/``Own`` markers and ``TokenLoader``.

A service gets a resolved :class:`Alias` per requirement and a
:class:`TokenLoader` for auth -- never the fakts client. What matters here is
that the markers carry the declaration, that ``Fakts`` satisfies the loader
protocol with no adapter, and that the auth link's stale-token path survives
being narrowed to it.
"""

from typing import Optional

import pytest

from fakts import Fakts, Own, Require, TokenLoader
from fakts.testing import build_testing_fakts


def test_require_keys_the_requirement_by_the_parameter_name():
    """The parameter name is the key -- that is what stops the two drifting."""
    requirement = Require("live.arkitekt.mikro", "Where the data lives").to_requirement("mikro")
    assert requirement.key == "mikro"
    assert requirement.service == "live.arkitekt.mikro"
    assert requirement.description == "Where the data lives"
    assert requirement.optional is False


def test_require_carries_optional():
    assert Require("live.arkitekt.s3", optional=True).to_requirement("s3").optional is True


def test_own_declares_nothing_to_provision():
    """unlok's shape: the app's own server is not a service a deployment composes."""
    assert not hasattr(Own(), "to_requirement")


def test_fakts_satisfies_the_token_loader_with_no_adapter():
    fakts = build_testing_fakts(aliases={})
    assert isinstance(fakts, TokenLoader)


@pytest.mark.asyncio
async def test_the_token_loader_gets_and_renews():
    async with build_testing_fakts(aliases={}, tokens=["a", "b"], token_lifetime=0) as fakts:
        loader: TokenLoader = fakts
        assert await loader.aget_token() == "a"
        assert await loader.arefresh_token(stale_token="a") == "b"


class _RecordingLoader:
    """A two-line stand-in -- the point of narrowing to a protocol."""

    def __init__(self) -> None:
        self.refreshed_with: list[Optional[str]] = []

    async def aget_token(self) -> str:
        return "stale-token"

    async def arefresh_token(self, stale_token: Optional[str] = None) -> str:
        self.refreshed_with.append(stale_token)
        return "fresh-token"


@pytest.mark.asyncio
async def test_a_401_refreshes_with_the_token_that_failed():
    """The regression this narrowing risks.

    rath's own ``ComposedAuthLink`` takes a refresher with no arguments. Losing
    the stale token would make every retry of one rejected operation rotate the
    refresh token again, instead of collapsing into a single renewal.
    """
    from fakts.contrib.rath.auth import FaktsAuthLink
    from rath.operation import Operation

    loader = _RecordingLoader()
    link = FaktsAuthLink(token_loader=loader)

    operation = Operation.model_construct(context=Operation.model_fields["context"].annotation())
    operation.context.headers = {"Authorization": "Bearer stale-token"}

    assert await link.arefresh_token(operation) == "fresh-token"
    assert loader.refreshed_with == ["stale-token"]


@pytest.mark.asyncio
async def test_a_bare_authorization_header_refreshes_with_none():
    from fakts.contrib.rath.auth import FaktsAuthLink
    from rath.operation import Operation

    loader = _RecordingLoader()
    link = FaktsAuthLink(token_loader=loader)

    operation = Operation.model_construct(context=Operation.model_fields["context"].annotation())
    operation.context.headers = {}

    await link.arefresh_token(operation)
    assert loader.refreshed_with == [None]
