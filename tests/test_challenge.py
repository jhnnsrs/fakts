"""Tests for signed alias challenges (instance challenge keys)."""

import base64
import sys
from typing import AsyncIterator, Awaitable, Callable, Tuple

import pytest
import pytest_asyncio
from aiohttp import web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from fakts_next import Fakts
from fakts_next.challenge import (
    CHALLENGE_DOMAIN,
    build_challenge_message,
    generate_nonce,
    verify_challenge_signature,
)
from fakts_next.errors import CompositionError, FaktsError
from fakts_next.models import ChallengeKey

from .test_fakts_behavior import CountingGrant, make_fakts_value, make_manifest

pytestmark = pytest.mark.asyncio


def make_keypair() -> Tuple[Ed25519PrivateKey, ChallengeKey]:
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private, ChallengeKey(key=base64.b64encode(raw).decode())


def sign_nonce(private: Ed25519PrivateKey, nonce: str) -> str:
    return base64.b64encode(private.sign(build_challenge_message(nonce))).decode()


async def test_verify_challenge_signature():
    private, key = make_keypair()
    _, other_key = make_keypair()

    signature = sign_nonce(private, "some-nonce")

    assert verify_challenge_signature(key, "some-nonce", signature)
    assert not verify_challenge_signature(key, "other-nonce", signature), (
        "A signature must not verify for a different nonce (replay)"
    )
    assert not verify_challenge_signature(other_key, "some-nonce", signature), (
        "A signature must not verify against another service's key"
    )
    assert not verify_challenge_signature(key, "some-nonce", "not base64!!"), (
        "Garbage signatures must fail, not raise"
    )
    assert not verify_challenge_signature(
        ChallengeKey(key="bm90IGEga2V5"), "some-nonce", signature
    ), "A malformed pinned key must fail the challenge"


Handler = Callable[[web.Request], Awaitable[web.Response]]


@pytest_asyncio.fixture
async def challenge_server() -> AsyncIterator[Callable[[Handler], Awaitable[int]]]:
    """Starts a local http server whose /test route is the alias's
    challenge path. The handler is provided by the test."""
    runners = []

    async def start(handler: Handler) -> int:
        app = web.Application()
        # make_fakts_value uses path="/test" and an empty challenge string,
        # so the alias's challenge path is /test itself
        app.router.add_get("/test", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        return runner.addresses[0][1]

    yield start

    for runner in runners:
        await runner.cleanup()


def make_pinned_fakts(port: int, key: ChallengeKey | None):
    """ActiveFakts with a single alias pointing at the local server."""
    value = make_fakts_value(host="127.0.0.1")
    instance = value.instances["test"]
    instance.challenge_key = key
    instance.aliases = [
        instance.aliases[0].model_copy(update={"port": port, "ssl": False})
    ]
    return value


async def test_signed_challenge_passes(challenge_server) -> None:
    private, key = make_keypair()

    async def handler(request: web.Request) -> web.Response:
        nonce = request.query["nonce"]
        return web.json_response({"signature": sign_nonce(private, nonce)})

    port = await challenge_server(handler)
    grant = CountingGrant(fakts=make_pinned_fakts(port, key))

    async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
        alias = await fakts.aget_alias("test", omit_report=True)

    assert alias.id == "primary"


async def test_unsigned_200_fails_when_key_is_pinned(challenge_server) -> None:
    """With a pinned key, a host that merely answers 200 must not pass."""
    _, key = make_keypair()

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    port = await challenge_server(handler)
    grant = CountingGrant(fakts=make_pinned_fakts(port, key))

    async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
        with pytest.raises(CompositionError, match="signature"):
            await fakts.aget_alias("test", omit_report=True)


async def test_wrong_key_signature_fails(challenge_server) -> None:
    """A host signing with a different key (impostor) must not pass."""
    impostor_private, _ = make_keypair()
    _, pinned_key = make_keypair()

    async def handler(request: web.Request) -> web.Response:
        nonce = request.query["nonce"]
        return web.json_response({"signature": sign_nonce(impostor_private, nonce)})

    port = await challenge_server(handler)
    grant = CountingGrant(fakts=make_pinned_fakts(port, pinned_key))

    async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
        with pytest.raises(CompositionError, match="invalid\\s+signature|identity key"):
            await fakts.aget_alias("test", omit_report=True)


async def test_plain_challenge_without_key_still_passes(challenge_server) -> None:
    """Instances without a challenge key keep the plain 200-check."""

    async def handler(request: web.Request) -> web.Response:
        assert "nonce" not in request.query, "No nonce should be sent without a key"
        return web.Response(text="ok")

    port = await challenge_server(handler)
    grant = CountingGrant(fakts=make_pinned_fakts(port, None))

    async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
        alias = await fakts.aget_alias("test", omit_report=True)

    assert alias.id == "primary"


async def test_missing_cryptography_raises_faktserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pinned key must never silently downgrade: if the optional
    'cryptography' package cannot be imported, verification raises FaktsError
    with an install hint rather than returning False."""
    _, key = make_keypair()

    # Force the in-function `from cryptography...ed25519 import ...` to fail.
    monkeypatch.setitem(
        sys.modules,
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        None,
    )

    with pytest.raises(FaktsError, match="cryptography"):
        verify_challenge_signature(key, "some-nonce", "c2ln")


async def test_generate_nonce_is_unique():
    nonces = {generate_nonce() for _ in range(100)}
    assert len(nonces) == 100, "Nonces must be fresh per probe"


async def test_build_challenge_message_is_domain_separated():
    assert build_challenge_message("abc") == b"fakts-challenge-v1:abc"
    assert build_challenge_message("abc") == f"{CHALLENGE_DOMAIN}:abc".encode()


async def test_unsupported_key_kind_falls_back_to_plain(challenge_server) -> None:
    """A key of an unknown kind (from a newer server) must not break the
    client; it falls back to the plain challenge with a warning."""

    async def handler(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    port = await challenge_server(handler)
    key = ChallengeKey(kind="post-quantum-9000", key="irrelevant")
    grant = CountingGrant(fakts=make_pinned_fakts(port, key))

    async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
        alias = await fakts.aget_alias("test", omit_report=True)

    assert alias.id == "primary"
