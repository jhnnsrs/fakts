"""Tests for signed alias challenges (instance challenge keys)."""

import asyncio
import base64
import socket
import ssl
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from aiohttp import web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from fakts import Fakts
from fakts.aliases import _classify
from fakts.challenge import (
    CHALLENGE_DOMAIN,
    build_challenge_message,
    generate_nonce,
    verify_challenge_signature,
)
from fakts.errors import (
    AliasAttempt,
    AttemptOutcome,
    ChallengeStatusError,
    CompositionError,
    FaktsError,
    ServiceFailure,
    ServiceUnreachableError,
)
from fakts.models import ChallengeKey

from .helpers import CountingGrant, make_fakts_value, make_manifest

pytestmark = pytest.mark.asyncio


def free_port() -> int:
    """A loopback port nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def make_keypair() -> tuple[Ed25519PrivateKey, ChallengeKey]:
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
    instance.aliases = [instance.aliases[0].model_copy(update={"port": port, "ssl": False})]
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
        with pytest.raises(CompositionError, match=r"invalid\s+signature|identity key"):
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


async def test_an_unsupported_key_kind_fails_closed(challenge_server) -> None:
    """A pinned key of a kind this fakts cannot verify must not downgrade to
    the plain challenge: the instance pinned a key so a 200 is not enough."""

    async def handler(request: web.Request) -> web.Response:
        return web.Response(text="ok")  # anyone can answer 200

    port = await challenge_server(handler)
    key = ChallengeKey(kind="post-quantum-9000", key="irrelevant")
    grant = CountingGrant(fakts=make_pinned_fakts(port, key))

    async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
        with pytest.raises(CompositionError, match=r"post-quantum-9000.*Upgrade fakts"):
            await fakts.aget_alias("test", omit_report=True)


# --- what a failed challenge is reported as ---------------------------------


async def failure_of(fakts: Fakts) -> ServiceFailure:
    with pytest.raises(CompositionError) as raised:
        await fakts.aget_alias("test", omit_report=True)
    (failure,) = raised.value.failures
    assert failure.key == "test" and failure.instance == "test_instance"
    assert failure.render() in str(raised.value)
    return failure


async def test_a_wrong_status_is_reported_as_one(challenge_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=503, text="starting")

    port = await challenge_server(handler)
    grant = CountingGrant(fakts=make_pinned_fakts(port, None))
    async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
        failure = await failure_of(fakts)
    (attempt,) = failure.attempts
    assert attempt.outcome is AttemptOutcome.BAD_STATUS
    assert attempt.url == f"http://127.0.0.1:{port}/test"
    assert "answered with status 503" in failure.render()
    assert "not as the service" in (failure.hint() or "")


async def test_nothing_listening_is_unreachable() -> None:
    port = free_port()
    grant = CountingGrant(fakts=make_pinned_fakts(port, None))
    async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
        failure = await failure_of(fakts)
    assert [a.outcome for a in failure.attempts] == [AttemptOutcome.UNREACHABLE]
    assert "running" in (failure.hint() or "")


async def test_no_answer_in_time_is_a_timeout(challenge_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        await asyncio.sleep(1)
        return web.Response(text="late")

    port = await challenge_server(handler)
    grant = CountingGrant(fakts=make_pinned_fakts(port, None))
    fakts = Fakts(grant=grant, manifest=make_manifest(), alias_challenge_timeout=0.2)
    async with fakts:
        failure = await failure_of(fakts)
    (attempt,) = failure.attempts
    assert attempt.outcome is AttemptOutcome.TIMEOUT
    assert attempt.describe().startswith("timed out after 0.")


async def test_unsigned_and_forged_answers_are_told_apart(challenge_server) -> None:
    impostor, _ = make_keypair()
    _, pinned = make_keypair()

    async def unsigned(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def forged(request: web.Request) -> web.Response:
        return web.json_response({"signature": sign_nonce(impostor, request.query["nonce"])})

    for handler, outcome in (
        (unsigned, AttemptOutcome.UNSIGNED),
        (forged, AttemptOutcome.BAD_SIGNATURE),
    ):
        port = await challenge_server(handler)
        grant = CountingGrant(fakts=make_pinned_fakts(port, pinned))
        async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
            failure = await failure_of(fakts)
        assert [a.outcome for a in failure.attempts] == [outcome]


async def test_a_forged_answer_is_warned_of_even_when_another_alias_works(
    challenge_server, caplog: pytest.LogCaptureFixture
) -> None:
    """The alias that works is used, but a host that answers for the service
    without its key is not something to pass over in silence."""
    genuine, pinned = make_keypair()
    impostor, _ = make_keypair()

    def signing(private: Ed25519PrivateKey) -> Handler:
        async def handler(request: web.Request) -> web.Response:
            return web.json_response({"signature": sign_nonce(private, request.query["nonce"])})

        return handler

    forged_port = await challenge_server(signing(impostor))
    genuine_port = await challenge_server(signing(genuine))
    value = make_pinned_fakts(forged_port, pinned)
    forged = value.instances["test"].aliases[0]
    value.instances["test"].aliases.append(
        forged.model_copy(update={"id": "genuine", "port": genuine_port})
    )

    with caplog.at_level("WARNING", logger="fakts.aliases"):
        async with Fakts(grant=CountingGrant(fakts=value), manifest=make_manifest()) as fakts:
            alias = await fakts.aget_alias("test", omit_report=True)
    assert alias.id == "genuine"
    (warning,) = [r.getMessage() for r in caplog.records if r.name == "fakts.aliases"]
    assert "primary" in warning and "does not verify" in warning


async def test_a_forged_answer_is_listed_first() -> None:
    failure = ServiceFailure(
        key="test",
        service="test_service",
        optional=False,
        instance="test_instance",
        attempts=(
            AliasAttempt("lan", None, "http://10.0.0.4/ht", AttemptOutcome.TIMEOUT, None, 3.0),
            AliasAttempt(
                "pub", None, "https://lab.example/ht", AttemptOutcome.BAD_SIGNATURE, "forged"
            ),
        ),
    )
    lines = failure.render().splitlines()
    assert lines[1].split() == ["-", "pub", "https://lab.example/ht", "forged"]
    assert lines[2].split()[:3] == ["-", "lan", "http://10.0.0.4/ht"]
    assert lines[2].endswith("timed out after 3.0 s")
    assert "does not verify" in lines[3]


async def test_a_challenge_that_says_no_is_still_an_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A challenger returning False used to leave no trace: 'all 2 aliases
    failed' over an empty list."""

    async def refuses(self: Fakts, alias: Any, challenge_key: object = None) -> bool:
        return False

    monkeypatch.setattr(Fakts, "_achallenge_alias", refuses)
    grant = CountingGrant(fakts=make_fakts_value())
    async with Fakts(grant=grant, manifest=make_manifest()) as fakts:
        failure = await failure_of(fakts)
    assert [(a.alias_id, a.outcome) for a in failure.attempts] == [
        ("primary", AttemptOutcome.REFUSED),
        ("fallback", AttemptOutcome.REFUSED),
    ]
    assert failure.render().count("failed its challenge") == 2


async def test_an_unreachable_optional_service_says_what_was_tried() -> None:
    value = make_pinned_fakts(free_port(), None)
    manifest = make_manifest()
    manifest.requirements[0].optional = True
    async with Fakts(grant=CountingGrant(fakts=value), manifest=manifest) as fakts:
        with pytest.raises(ServiceUnreachableError) as raised:
            await fakts.aget_alias("test", omit_report=True)
        assert raised.value.failure.optional
        assert raised.value.failure.has(AttemptOutcome.UNREACHABLE)
        assert await fakts.aget_alias_or_none("test", omit_report=True) is None
        assert fakts.report_map["test"].reason == raised.value.failure.render()


def test_the_errors_survive_a_pickle() -> None:
    """They cross process boundaries (an actor's error, a worker's)."""
    import pickle

    failure = ServiceFailure(key="test", service="test_service", optional=True, reason="down")
    unreachable = pickle.loads(pickle.dumps(ServiceUnreachableError("no alias", failure)))
    assert str(unreachable) == "no alias" and unreachable.failure == failure
    composition = pickle.loads(pickle.dumps(CompositionError("all down", (failure,))))
    assert str(composition) == "all down" and composition.failures == (failure,)
    status = pickle.loads(pickle.dumps(ChallengeStatusError("bad", status=503, body="x")))
    assert (str(status), status.status, status.body) == ("bad", 503, "x")


def test_a_certificate_error_is_not_just_unreachable() -> None:
    """aiohttp's certificate errors are connection errors too: the order of
    the checks is what tells them apart."""
    assert _classify(ssl.SSLCertVerificationError("certificate verify failed"))[0] is (
        AttemptOutcome.TLS
    )
    assert _classify(ConnectionRefusedError("refused"))[0] is AttemptOutcome.UNREACHABLE
    assert _classify(TimeoutError())[0] is AttemptOutcome.TIMEOUT
    assert _classify(ValueError("odd")) == (AttemptOutcome.ERROR, "ValueError: odd")
