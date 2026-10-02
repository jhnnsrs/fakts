"""Docker aliases: only reachable from inside the deployment's own docker
environment. The server hands them to every client; where they sit in the
order depends on whether this process runs in a container, and the challenge
decides.
"""

from typing import Any

import pytest

from fakts import Fakts, aliases
from fakts.errors import CompositionError
from fakts.models import ActiveFakts, Alias, Instance

from .helpers import CountingGrant, make_fakts_value, make_manifest


def docker_fakts(*order: str) -> ActiveFakts:
    """One instance with a docker and a direct alias, listed in ``order``."""
    known = {
        "docker": Alias(
            id="docker", host="gateway", port=80, path="/test", challenge="ht", kind="docker"
        ),
        "direct": Alias(id="direct", host="localhost", port=1, path="/test", challenge="ht"),
    }
    value = make_fakts_value()
    value.auth.report_endpoint = None
    value.instances["test"] = Instance(
        service="test_service",
        identifier="test_instance",
        aliases=[known[name] for name in order],
    )
    return value


def recording_challenge(probed: list[str], *reachable: str) -> Any:
    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None, **kw: Any) -> bool:
        probed.append(alias.id)
        return alias.id in reachable

    return challenge


def place(monkeypatch: pytest.MonkeyPatch, *, container: bool) -> None:
    monkeypatch.setattr(aliases, "in_container", lambda: container)


async def resolve(value: ActiveFakts, **kwargs: Any) -> Alias:
    fakts = Fakts(grant=CountingGrant(fakts=value), manifest=make_manifest())
    async with fakts:
        return await fakts.aget_alias("test", omit_report=True, **kwargs)


@pytest.mark.asyncio
async def test_in_a_container_the_docker_alias_is_tried_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probed: list[str] = []
    place(monkeypatch, container=True)
    monkeypatch.setattr(Fakts, "_achallenge_alias", recording_challenge(probed, "docker", "direct"))

    alias = await resolve(docker_fakts("direct", "docker"))

    assert alias.id == "docker"
    assert probed == ["docker"]


@pytest.mark.asyncio
async def test_a_container_elsewhere_falls_back_to_the_direct_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A container is not necessarily one of that deployment: the challenge decides."""
    probed: list[str] = []
    place(monkeypatch, container=True)
    monkeypatch.setattr(Fakts, "_achallenge_alias", recording_challenge(probed, "direct"))

    alias = await resolve(docker_fakts("docker", "direct"))

    assert alias.id == "direct"
    assert probed == ["docker", "direct"]


@pytest.mark.asyncio
async def test_outside_a_container_the_docker_alias_is_not_probed_when_another_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probed: list[str] = []
    place(monkeypatch, container=False)
    monkeypatch.setattr(Fakts, "_achallenge_alias", recording_challenge(probed, "docker", "direct"))

    alias = await resolve(docker_fakts("docker", "direct"))

    assert alias.id == "direct"
    assert probed == ["direct"]


@pytest.mark.asyncio
async def test_outside_a_container_the_docker_alias_is_the_last_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not being detected as a container never makes the alias unusable."""
    probed: list[str] = []
    place(monkeypatch, container=False)
    monkeypatch.setattr(Fakts, "_achallenge_alias", recording_challenge(probed, "docker"))

    alias = await resolve(docker_fakts("docker", "direct"))

    assert alias.id == "docker"
    assert probed == ["direct", "docker"]


@pytest.mark.asyncio
async def test_unchallenged_a_docker_alias_is_never_picked_over_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the probe nothing tells that this container is in the deployment."""
    place(monkeypatch, container=True)

    alias = await resolve(docker_fakts("docker", "direct"), omit_challenge=True)

    assert alias.id == "direct"


@pytest.mark.asyncio
async def test_unchallenged_a_lone_docker_alias_is_still_the_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    place(monkeypatch, container=False)

    alias = await resolve(docker_fakts("docker"), omit_challenge=True)

    assert alias.id == "docker"


@pytest.mark.asyncio
async def test_an_unreachable_docker_alias_fails_like_any_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probed: list[str] = []
    place(monkeypatch, container=False)
    monkeypatch.setattr(Fakts, "_achallenge_alias", recording_challenge(probed))

    with pytest.raises(CompositionError):
        await resolve(docker_fakts("docker", "direct"))

    assert probed == ["direct", "docker"]


def test_a_container_is_recognised_by_its_marker_file(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / ".dockerenv"
    monkeypatch.setattr(aliases, "_CONTAINER_MARKERS", (str(marker),))

    assert aliases.in_container() is False
    marker.touch()
    assert aliases.in_container() is True
