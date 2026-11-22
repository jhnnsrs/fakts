"""The server ranks an instance's aliases; the client follows that, narrowed by its own alias
policy, and uses plain HTTP on a strict instance only where it never leaves the machine, the
deployment's network or the mesh."""

from pathlib import Path

import pytest

from fakts import aliases
from fakts.models import Alias, AliasPolicy, Instance, TlsClaim

HUB = (Path(__file__).parent / "fixtures" / "hub.crt").read_text()


def alias(id: str, *, reach: str, ssl: bool = True, priority: int | None = None) -> Alias:
    return Alias(id=id, host=f"{id}.example", ssl=ssl, challenge="ht", reach=reach, priority=priority)


def instance(*listed: Alias, preferred: str | None = None) -> Instance:
    return Instance(service="s", identifier="i", aliases=list(listed), preferred_alias=preferred)


def order(view: Instance) -> list[str]:
    return [a.id for a in view.aliases]


def test_the_server_ranks_and_the_last_working_alias_only_breaks_ties() -> None:
    ranked = instance(
        alias("public", reach="public", priority=50),
        alias("lan", reach="lan", priority=30),
        alias("lan-2", reach="lan", priority=30),
        preferred="public",
    )
    # The preferred alias does not jump the server's ranking...
    assert order(aliases.ranked_view(ranked)) == ["lan", "lan-2", "public"]
    # ...it goes first among those ranked alike.
    assert order(aliases.ranked_view(ranked.model_copy(update={"preferred_alias": "lan-2"}))) == [
        "lan-2",
        "lan",
        "public",
    ]
    # A server that sends no priority: the preferred alias first, then the server's order.
    unranked = instance(alias("a", reach="lan"), alias("b", reach="lan"), alias("c", reach="lan"), preferred="c")
    assert order(aliases.ranked_view(unranked)) == ["c", "a", "b"]


def test_the_client_policy_only_narrows_and_reorders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKTS_ALIAS_PREFER_REACH", "public")
    monkeypatch.setenv("FAKTS_ALIAS_EXCLUDE_REACH", "mesh")
    monkeypatch.setenv("FAKTS_ALIAS_EXCLUDE", "lan-2")
    policy = AliasPolicy.from_env()
    ranked = instance(
        alias("lan", reach="lan", priority=30),
        alias("lan-2", reach="lan", priority=31),
        alias("mesh", reach="mesh", ssl=False, priority=40),
        alias("public", reach="public", priority=50),
    )
    assert order(aliases.ranked_view(ranked, policy)) == ["public", "lan"]


def test_a_strict_instance_keeps_plain_http_only_where_it_never_leaves_the_machine_or_network() -> None:
    strict = instance(
        alias("loopback+http", reach="loopback", ssl=False),
        alias("internal+http", reach="internal", ssl=False),
        alias("lan+http", reach="lan", ssl=False),
        alias("lan", reach="lan"),
    ).model_copy(update={"tls": TlsClaim(certificates=[HUB])})
    view = aliases.strict_view(strict)
    assert [(a.id, a.is_pinned()) for a in view.aliases] == [
        ("loopback+http", False),
        ("internal+http", False),
        ("lan", True),
    ]
