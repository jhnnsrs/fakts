"""A strict instance — its hub registered its certificate — is used by its TLS aliases, each
verified by that certificate alone, and by plain ones only over the mesh."""

from pathlib import Path
from typing import Any

import pytest

from fakts import Fakts, aliases
from fakts.models import ActiveFakts, Alias, Instance, TlsClaim

from .helpers import CountingGrant, make_fakts_value, make_manifest

HUB = (Path(__file__).parent / "fixtures" / "hub.crt").read_text()


def strict_fakts(*, certificates: list[str] | None = None) -> ActiveFakts:
    value = make_fakts_value()
    value.auth.report_endpoint = None
    value.instances["test"] = Instance(
        service="test_service",
        identifier="test_instance",
        aliases=[
            Alias(id="lab", host="lab.local", port=443, path="/test", challenge="ht", ssl=True),
            Alias(id="lab+http", host="lab.local", port=80, path="/test", challenge="ht"),
            Alias(
                id="mesh",
                host="hub.tail.ts.net",
                port=80,
                path="/test",
                challenge="ht",
                kind="mesh",
            ),
        ],
        tls=TlsClaim(certificates=certificates if certificates is not None else [HUB]),
    )
    return value


def recording(seen: list[tuple[str, bool]], *answering: str) -> Any:
    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None, **kw: Any) -> bool:
        seen.append((alias.id, alias.is_pinned()))
        return alias.id in answering

    return challenge


async def resolve(value: ActiveFakts) -> Alias:
    fakts = Fakts(grant=CountingGrant(fakts=value), manifest=make_manifest())
    async with fakts:
        return await fakts.aget_alias("test", omit_report=True)


def test_the_strict_view_pins_tls_and_keeps_plain_only_on_the_mesh() -> None:
    view = aliases.strict_view(strict_fakts().instances["test"])
    assert [(a.id, a.is_pinned()) for a in view.aliases] == [("lab", True), ("mesh", False)]
    assert view.aliases[0].certificates == [HUB]


def test_an_instance_without_a_certificate_is_left_alone() -> None:
    instance = strict_fakts(certificates=[]).instances["test"]
    assert not instance.is_strict()
    assert aliases.strict_view(instance) is instance


@pytest.mark.asyncio
async def test_the_tls_alias_is_challenged_and_handed_on_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(Fakts, "_achallenge_alias", recording(seen, "lab", "lab+http"))

    alias = await resolve(strict_fakts())

    assert alias.id == "lab"
    assert alias.is_pinned() and alias.certificates == [HUB]
    assert ("lab", True) in seen
    assert all(id != "lab+http" for id, _ in seen)


@pytest.mark.asyncio
async def test_a_plain_alias_off_the_mesh_is_never_used_even_when_it_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fakts.errors import CompositionError

    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(Fakts, "_achallenge_alias", recording(seen, "lab+http"))

    with pytest.raises(CompositionError):
        await resolve(strict_fakts())
    assert all(id != "lab+http" for id, _ in seen)


def test_a_rotated_certificate_is_a_changed_instance() -> None:
    before = strict_fakts().instances["test"]
    after = before.model_copy(
        update={
            "tls": TlsClaim(
                certificates=["-----BEGIN CERTIFICATE-----\nAA==\n-----END CERTIFICATE-----"]
            )
        }
    )
    assert aliases._same_instance(before, before)
    assert not aliases._same_instance(before, after)


@pytest.mark.asyncio
async def test_a_pinned_challenge_runs_over_tls_verified_by_the_hub_certificate() -> None:
    import ssl

    from aiohttp import web

    fixtures = Path(__file__).parent / "fixtures"
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(fixtures / "hub.crt", fixtures / "hub.key")
    app = web.Application()
    app.router.add_get("/test/ht", lambda request: web.Response(text="ok"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_tls)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        fakts = Fakts(grant=CountingGrant(fakts=strict_fakts()), manifest=make_manifest())
        at = dict(id="lab", host="localhost", port=port, path="/test", challenge="ht", ssl=True)
        assert await fakts._achallenge_alias(Alias(**at, certificates=[HUB]))
        # The same server, not pinned: the public roots do not know it.
        with pytest.raises(Exception, match=r"(?i)certificate"):
            await fakts._achallenge_alias(Alias(**at))
    finally:
        await runner.cleanup()
