"""Plain HTTP off this machine and off the mesh is said to be insecure, once per alias.

A challenge key does not make it secure: the signed nonce proves the service answered the
probe, not who answers what follows. Loopback never leaves the machine and the mesh is
encrypted itself, so those are not reported.
"""

import logging

import pytest

from fakts import aliases
from fakts.models import Alias


def alias(host: str, *, ssl: bool = False, kind: str | None = None, id: str = "a") -> Alias:
    return Alias(id=id, host=host, port=80, path="/mikro", challenge="ht", ssl=ssl, kind=kind)


@pytest.mark.parametrize(
    "host", ["10.0.0.4", "lab.local", "140.78.80.150", "gateway"]
)  # gateway: not marked docker
def test_plain_http_to_another_machine_is_insecure(host: str) -> None:
    assert aliases.is_insecure_transport(alias(host))


@pytest.mark.parametrize(
    "host", ["localhost", "LocalHost.", "app.localhost", "127.0.0.1", "127.3.4.5", "::1", "[::1]"]
)
def test_loopback_is_not(host: str) -> None:
    assert not aliases.is_insecure_transport(alias(host))


def test_tls_the_mesh_and_docker_are_not() -> None:
    assert not aliases.is_insecure_transport(alias("lab.local", ssl=True))
    assert not aliases.is_insecure_transport(alias("hub.tailnet.ts.net", kind="mesh"))
    assert not aliases.is_insecure_transport(alias("gateway", kind="docker"))


def test_it_is_said_at_info_once_per_alias(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(aliases, "_noted_insecure", set())
    with caplog.at_level(logging.INFO, logger="fakts.aliases"):
        aliases._note_transport("mikro", alias("10.0.0.4"))
        aliases._note_transport("mikro", alias("10.0.0.4"))
        aliases._note_transport("mikro", alias("localhost", id="local"))
        aliases._note_transport("mikro", alias("lab.local", ssl=True, id="tls"))

    notes = [r for r in caplog.records if "plain HTTP" in r.getMessage()]
    assert len(notes) == 1
    assert notes[0].levelno == logging.INFO
    assert "http://10.0.0.4:80/mikro" in notes[0].getMessage()
    assert "challenge signature" in notes[0].getMessage()


def test_a_reach_the_server_says_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    """With an arkitekt-spec that reads ``reach``; an older one leaves it out and ``kind`` decides."""
    said = lambda host, reach: alias(host).model_copy(update={"reach": reach})  # noqa: E731
    if "reach" not in Alias.model_fields:
        pytest.skip("this arkitekt-spec does not read reach yet")
    assert not aliases.is_insecure_transport(said("gateway", "internal"))
    assert not aliases.is_insecure_transport(said("hub.tail.ts.net", "mesh"))
    assert aliases.is_insecure_transport(said("10.0.0.4", "lan"))
    assert aliases.is_insecure_transport(said("lab.example.org", "public"))
