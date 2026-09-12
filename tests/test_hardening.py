"""Regression tests for the audit findings.

Each of these asserts a specific failure mode that was verified to exist
before the fix. They are grouped by what they protect, not by module.
"""

import asyncio
import logging
import os
import ssl
import stat
import time
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional

import pytest
import pytest_asyncio
from aiohttp import web
from pydantic import BaseModel

from fakts import Fakts
from fakts.cache import file as file_cache
from fakts.cache.file import FileCache
from fakts.errors import NeedsReauthenticationError
from fakts.grants.env import EnvGrant
from fakts.grants.hard import HardFaktsGrant
from fakts.grants.remote.authorizers.device_code import DeviceCodeAuthorizer
from fakts.models import (
    ActiveFakts,
    Alias,
    AuthFakt,
    ChallengeKey,
    Instance,
    Manifest,
    PublicSource,
    Requirement,
    SelfFakt,
)
from fakts.oauth2 import InsecureTransportError, check_transport

from .test_fakts_behavior import make_fakts_value, make_manifest

pytestmark = pytest.mark.asyncio


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@pytest_asyncio.fixture
async def server() -> AsyncIterator[Callable[..., Awaitable[str]]]:
    runners = []

    async def start(routes: dict[str, Handler], method: str = "GET") -> str:
        app = web.Application()
        for path, handler in routes.items():
            app.router.add_route(method, path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        return f"http://127.0.0.1:{runner.addresses[0][1]}"

    yield start

    for runner in runners:
        await runner.cleanup()


class Grant(BaseModel):
    fakts: ActiveFakts
    load_count: int = 0
    requires_user_interaction: bool = True

    async def aload(self) -> ActiveFakts:
        self.load_count += 1
        return self.fakts


# --------------------------------------------------------------------------- #
# Alias challenge integrity
# --------------------------------------------------------------------------- #


async def test_challenge_does_not_follow_redirects(server) -> None:
    """The signed message commits only to the nonce, so a host that bounces
    the probe to the real service would have it sign our nonce and pass.
    Refusing redirects removes the zero-effort version of that."""
    signed_by_real_service = {"hit": False}

    async def impostor(request: web.Request) -> web.Response:
        nonce = request.query.get("nonce", "")
        raise web.HTTPFound(f"/real?nonce={nonce}")

    async def real(request: web.Request) -> web.Response:
        signed_by_real_service["hit"] = True
        return web.json_response({"signature": "whatever"})

    base = await server({"/challenge": impostor, "/real": real})
    port = int(base.rsplit(":", 1)[1])

    fakts = Fakts(grant=Grant(fakts=make_fakts_value()), manifest=make_manifest())
    alias = Alias(id="a", host="127.0.0.1", port=port, challenge="challenge")

    async with fakts:
        with pytest.raises(Exception):
            await fakts.achallenge_alias(alias)

    assert not signed_by_real_service["hit"], (
        "the probe was relayed to the genuine service — a redirector could "
        "satisfy the challenge and still receive all the traffic"
    )


async def test_omit_challenge_does_not_disable_later_verification(
    monkeypatch,
) -> None:
    """One omit_challenge=True call used to poison the alias cache for the
    whole process, skipping the pinned-key check for every later caller."""
    challenged: list[str] = []

    async def fake_challenge(self, alias, challenge_key=None) -> bool:
        challenged.append(alias.id)
        return True

    monkeypatch.setattr(Fakts, "achallenge_alias", fake_challenge)

    value = make_fakts_value()
    value.instances["test"].challenge_key = ChallengeKey(kind="ed25519", key="AAAA")

    fakts = Fakts(grant=Grant(fakts=value), manifest=make_manifest())

    async with fakts:
        await fakts.aget_alias("test", omit_challenge=True, omit_report=True)
        assert challenged == [], "omit_challenge must not probe"

        await fakts.aget_alias("test", omit_report=True)
        assert challenged, "a caller that wants a challenge must get one"

        before = len(challenged)
        await fakts.aget_alias("test", omit_report=True)
        assert len(challenged) == before, "a challenged alias should still cache"


# --------------------------------------------------------------------------- #
# Credential disclosure
# --------------------------------------------------------------------------- #


async def test_cache_load_error_does_not_log_the_token(tmp_path: Path, caplog) -> None:
    """A corrupt cache is logged on every start; the log must not carry the
    credential that made it corrupt."""
    secret = "v1.SUPERSECRET_REFRESH_TOKEN_ABCDEFGHIJKLMNOP"
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        '{"fakts": {"self": {"deployment_name": "d", "alias": {"id": "a", "host": "h"}},'
        ' "auth": {"client_id": "c", "refresh_token": "' + secret + '"},'
        ' "instances": {}, "statuses": {}}, "created": "2026-01-01T00:00:00", "hash": ""}'
    )

    with caplog.at_level("DEBUG"):
        assert await FileCache(cache_file=str(cache_file)).aload() is None

    assert secret not in caplog.text


# --------------------------------------------------------------------------- #
# Transport gating
# --------------------------------------------------------------------------- #


async def test_insecure_transport_env_var_respects_falsey_values(monkeypatch) -> None:
    """FAKTS_ALLOW_INSECURE_TRANSPORT=0 must not *enable* insecure transport."""
    url = "http://some-lan-box:8000/o/token/"

    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("FAKTS_ALLOW_INSECURE_TRANSPORT", value)
        with pytest.raises(InsecureTransportError):
            check_transport(url, False)

    monkeypatch.setenv("FAKTS_ALLOW_INSECURE_TRANSPORT", "1")
    check_transport(url, False)  # must not raise


async def test_report_is_skipped_over_untrusted_transport(monkeypatch) -> None:
    """The report carries the access token, so it gets the same gate as the
    token endpoint. It used to be the one credential-bearing call without one."""
    import aiohttp

    posted: list[str] = []
    real_post = aiohttp.ClientSession.post

    def spy(self, url, *args, **kwargs):
        posted.append(str(url))
        return real_post(self, url, *args, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "post", spy)

    # Same origin as the token endpoint, so *only* the transport gate can
    # stop this — otherwise the origin check would mask it.
    value = make_fakts_value()
    value.auth.token_endpoint = "http://some-lan-box:8000/o/token/"
    value.auth.report_endpoint = "http://some-lan-box:8000/f/report/"

    fakts = Fakts(grant=Grant(fakts=value), manifest=make_manifest())
    async with fakts:
        await fakts._areport_aliases(value, [], "an-access-token")

    assert posted == [], f"the access token was sent over plain http: {posted}"


async def test_report_over_https_is_sent(monkeypatch) -> None:
    """The gate must not simply disable reporting everywhere."""
    import aiohttp

    posted: list[str] = []
    real_post = aiohttp.ClientSession.post

    def spy(self, url, *args, **kwargs):
        posted.append(str(url))
        return real_post(self, url, *args, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "post", spy)

    value = make_fakts_value()
    value.auth.token_endpoint = "https://example.com/o/token/"
    value.auth.report_endpoint = "https://example.com/f/report/"

    fakts = Fakts(grant=Grant(fakts=value), manifest=make_manifest())
    async with fakts:
        await fakts._areport_aliases(value, [], "an-access-token")

    assert posted == ["https://example.com/f/report/"]


async def test_report_is_skipped_when_origin_differs() -> None:
    """A report endpoint on a different origin than the token endpoint would
    send the bearer token somewhere the app never authenticated against."""
    value = make_fakts_value()
    value.auth.token_endpoint = "https://real.example.com/o/token/"
    value.auth.report_endpoint = "https://attacker.example.com/f/report/"

    fakts = Fakts(grant=Grant(fakts=value), manifest=make_manifest())
    async with fakts:
        # Reaches the origin check and returns without attempting a request.
        await fakts._areport_aliases(value, [], "an-access-token")


@pytest.mark.parametrize(
    "uri,should_open",
    [
        ("https://example.com/configure/ABC", True),
        ("http://example.com/configure/ABC", True),
        ("file:///etc/passwd", False),
        ("javascript:alert(1)", False),
        ("customscheme://do-something", False),
    ],
)
async def test_browser_only_opens_http_urls(server, monkeypatch, uri, should_open) -> None:
    """webbrowser hands unknown schemes to the desktop's handler, so a
    hostile endpoint could otherwise get file:// invoked."""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open_new", lambda url: opened.append(url))

    async def authorize(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "granted",
                "device_code": "d",
                "user_code": "U",
                "client_id": "c",
                "verification_uri_complete": uri,
                "expires_in": 1,
                "interval": 1,
            }
        )

    async def token(request: web.Request) -> web.Response:
        return web.json_response({"error": "access_denied"}, status=400)

    base = await server(
        {"/o/app-authorization/": authorize, "/o/token/": token}, method="POST"
    )

    from fakts.grants.remote.errors import UserDeniedError
    from fakts.grants.remote.models import FaktsEndpoint

    endpoint = FaktsEndpoint(
        base_url=base + "/",
        name="T",
        protocol_version="2",
        token_endpoint=f"{base}/o/token/",
        device_authorization_endpoint=f"{base}/o/app-authorization/",
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    authorizer = DeviceCodeAuthorizer(
        manifest=make_manifest(), sleeper=no_sleep, allow_insecure_transport=True
    )

    with pytest.raises(UserDeniedError):
        await authorizer.aauthorize(endpoint)

    assert (opened == [uri]) is should_open, f"opened={opened} for {uri}"


# --------------------------------------------------------------------------- #
# Cache trust
# --------------------------------------------------------------------------- #


_posix_only = pytest.mark.skipif(
    os.name != "posix", reason="POSIX permission semantics"
)


def _loose_dir(tmp_path: Path, mode: int = 0o775) -> Path:
    """A directory with permissions the suite would otherwise never produce.

    pytest's own ``tmp_path`` is 0700, which is why a check that misfired on
    every Linux desktop shipped green: no test ever sat in a loose directory.
    """
    d = tmp_path / "loose"
    d.mkdir()
    os.chmod(d, mode)
    return d


async def _seeded_cache(directory: Path) -> FileCache:
    cache = FileCache(cache_file=str(directory / "cache.json"))
    await cache.aset(make_fakts_value())
    return cache


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


# --- the false alarm this whole area exists to have stopped emitting -------- #


@_posix_only
async def test_group_writable_dir_with_self_only_group_loads_silently(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported bug. `umask 002` plus a user-private group makes every
    directory an app creates 0775 with a single-member group, and the old
    predicate called that "writable by other users" and refused to read."""
    monkeypatch.setattr(file_cache, "_group_may_contain_others", lambda *_: False)
    cache = await _seeded_cache(_loose_dir(tmp_path))

    with caplog.at_level(logging.DEBUG, logger="fakts.cache.file"):
        assert await cache.aload() is not None

    assert _warnings(caplog) == []


@_posix_only
async def test_group_writable_dir_with_populated_group_warns_but_loads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A group with real other members is a real finding -- but a finding is
    all it is now, because refusing re-runs the grant and hangs scripts."""
    monkeypatch.setattr(file_cache, "_group_may_contain_others", lambda *_: True)
    cache = await _seeded_cache(_loose_dir(tmp_path))

    with caplog.at_level(logging.DEBUG, logger="fakts.cache.file"):
        assert await cache.aload() is not None

    (message,) = _warnings(caplog)
    assert "chmod g-w" in message


@_posix_only
async def test_unresolvable_gid_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gid we cannot enumerate is assumed shared: on an LDAP box it may name
    a real, populated group. Guessing loud costs one log line now."""

    def explode(_: int) -> object:
        raise KeyError("no such gid")

    monkeypatch.setattr(file_cache.grp, "getgrgid", explode)
    cache = await _seeded_cache(_loose_dir(tmp_path))

    with caplog.at_level(logging.DEBUG, logger="fakts.cache.file"):
        assert await cache.aload() is not None

    assert any("chmod g-w" in m for m in _warnings(caplog))


async def test_self_only_group_resolves_as_no_other_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`gr_mem` lists supplementary members only, so a user's primary group
    reads as empty -- exactly the case that must not be a finding."""

    class Group:
        gr_name = "jhnnsrs"
        gr_mem: list[str] = []

    class User:
        pw_name = "jhnnsrs"

    monkeypatch.setattr(file_cache.grp, "getgrgid", lambda _: Group())
    monkeypatch.setattr(file_cache.pwd, "getpwuid", lambda _: User())

    assert file_cache._group_may_contain_others(1000, 1000) is False


@_posix_only
async def test_sticky_other_writable_dir_is_silent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The /tmp case: with the sticky bit set, only the owner may replace an
    entry, so world-writable says nothing about who can swap our cache."""
    cache = await _seeded_cache(_loose_dir(tmp_path, 0o1777))

    with caplog.at_level(logging.DEBUG, logger="fakts.cache.file"):
        assert await cache.aload() is not None

    assert _warnings(caplog) == []


@_posix_only
async def test_other_writable_dir_without_sticky_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache = await _seeded_cache(_loose_dir(tmp_path, 0o777))

    with caplog.at_level(logging.DEBUG, logger="fakts.cache.file"):
        assert await cache.aload() is not None

    assert any("chmod o-w" in m for m in _warnings(caplog))


# --- the posture change: permissions report, they do not gate -------------- #


@_posix_only
async def test_world_writable_cache_warns_loads_and_is_tightened(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Replaces `test_world_writable_cache_is_refused`.

    A world-writable cache is still a genuine finding and still warns, but it
    no longer denies the read -- a denial returns a cache miss, and a miss
    re-runs the grant into a device-code prompt that hangs unattended
    clients. It is healed back to 0600 instead, which is a fix rather than a
    report. The order matters: tightening before the diagnostic would erase
    the very finding it is meant to surface.
    """
    directory = _loose_dir(tmp_path, 0o700)
    cache = await _seeded_cache(directory)
    cache_file = directory / "cache.json"
    os.chmod(cache_file, 0o666)

    with caplog.at_level(logging.DEBUG, logger="fakts.cache.file"):
        assert await cache.aload() is not None

    assert any("chmod o-w" in m for m in _warnings(caplog))
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600


@_posix_only
async def test_foreign_owner_warns_but_loads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cache owned by another uid is the one genuinely exploitable case --
    whoever owns it picks the token endpoint. It is a deliberate decision that
    it warns rather than refuses; the compensating control is that the cache
    now lives in a private per-user directory. A foreign file is also not ours
    to chmod, so the mode must be left alone."""
    directory = _loose_dir(tmp_path, 0o700)
    cache = await _seeded_cache(directory)
    cache_file = directory / "cache.json"
    os.chmod(cache_file, 0o640)
    monkeypatch.setattr(os, "getuid", lambda: os.stat(cache_file).st_uid + 1)

    with caplog.at_level(logging.DEBUG, logger="fakts.cache.file"):
        assert await cache.aload() is not None

    assert any("not by this user" in m for m in _warnings(caplog))
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o640


@_posix_only
async def test_group_writable_cache_file_is_tightened(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Benign group, so nothing to report -- but the file is still narrowed,
    because the self-heal is now the strongest control left on an existing
    file."""
    monkeypatch.setattr(file_cache, "_group_may_contain_others", lambda *_: False)
    directory = _loose_dir(tmp_path, 0o700)
    cache = await _seeded_cache(directory)
    cache_file = directory / "cache.json"
    os.chmod(cache_file, 0o660)

    with caplog.at_level(logging.DEBUG, logger="fakts.cache.file"):
        assert await cache.aload() is not None

    assert _warnings(caplog) == []
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600


@_posix_only
async def test_symlinked_cache_is_reported_as_a_symlink(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """O_NOFOLLOW already makes this read fail; the point is that it now says
    so, instead of surfacing as a generic "could not load"."""
    real = await _seeded_cache(_loose_dir(tmp_path, 0o700))
    link = tmp_path / "link.json"
    link.symlink_to(real.cache_file)

    with caplog.at_level(logging.DEBUG, logger="fakts.cache.file"):
        assert await FileCache(cache_file=str(link)).aload() is None

    assert any("is a symlink" in m for m in _warnings(caplog))


@_posix_only
async def test_diagnostic_does_not_chmod_the_containing_directory(
    tmp_path: Path,
) -> None:
    """`cache_file` is relative by default, so the containing directory is
    routinely a project root or a source checkout -- fakts has no standing to
    narrow it on a read. Narrowing belongs to whoever *creates* the directory
    (`ensure_private_dir`)."""
    directory = _loose_dir(tmp_path)
    cache = await _seeded_cache(directory)

    assert await cache.aload() is not None
    assert stat.S_IMODE(directory.stat().st_mode) == 0o775


# --------------------------------------------------------------------------- #
# Unattended recovery
# --------------------------------------------------------------------------- #


async def test_env_and_hard_grants_are_non_interactive() -> None:
    """Without this, a container gets 'needs someone at a browser' for a
    credential it could simply have re-read."""
    assert EnvGrant().requires_user_interaction is False
    assert HardFaktsGrant(fakts=make_fakts_value()).requires_user_interaction is False


async def test_hard_grant_does_not_hand_out_its_own_object() -> None:
    """Alias reordering mutates in place, so returning the caller's object
    lets one Fakts reorder another's configuration."""
    value = make_fakts_value()
    grant = HardFaktsGrant(fakts=value)
    loaded = await grant.aload()
    loaded.instances["test"].aliases.reverse()
    assert value.instances["test"].aliases[0].id == "primary"


async def test_env_grant_recovers_unattended_when_credential_ages(
    monkeypatch, tmp_path: Path
) -> None:
    """An aged env credential must reload from the environment rather than
    raise — that is the whole headless story."""
    import json

    from fakts.fakts import REFRESH_TOKEN_MAX_AGE

    fresh = make_fakts_value(refresh_token="from_env")
    fresh.auth.refresh_issued_at = time.time()
    fresh.auth.token_endpoint = "https://example.com/o/token/"

    path = tmp_path / "fakts.json"
    path.write_text(fresh.model_dump_json())
    monkeypatch.delenv("FAKTS", raising=False)
    monkeypatch.setenv("FAKTS_FILE", str(path))

    aged = make_fakts_value(refresh_token="aged")
    aged.auth.refresh_issued_at = time.time() - REFRESH_TOKEN_MAX_AGE - 60
    aged.auth.access_token = None

    fakts = Fakts(grant=EnvGrant(), manifest=make_manifest())
    async with fakts:
        fakts.loaded_fakts = aged
        # Must not raise NeedsReauthenticationError: the grant is unattended.
        try:
            await fakts.aget_token()
        except NeedsReauthenticationError:
            pytest.fail("a non-interactive grant must recover without a human")
        except Exception:
            # A network failure reaching the (fake) token endpoint is fine —
            # what matters is that we got past the interactive gate.
            pass


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


async def test_fakts_is_unusable_after_exit() -> None:
    from fakts.errors import NotEnteredError

    fakts = Fakts(grant=Grant(fakts=make_fakts_value()), manifest=make_manifest())
    async with fakts:
        await fakts.aload()

    with pytest.raises(NotEnteredError):
        await fakts.aget_alias("test", omit_challenge=True, omit_report=True)


async def test_failed_enter_does_not_leak_the_context_variable() -> None:
    from fakts import get_current_fakts
    from fakts.errors import NoFaktsFound

    class StaticGrant(BaseModel):
        requires_user_interaction: bool = False

        async def aload(self) -> ActiveFakts:
            return make_fakts_value()

    class ExplodingCache(BaseModel):
        """Fails when __aenter__ binds the manifest hash to it.

        The grant no longer runs on enter, so the cache-hash binding is the
        remaining step that can fail after the contextvar is already set —
        which is the condition this test exists to pin.
        """

        hash: str = ""

        def __setattr__(self, name: str, value: object) -> None:
            if name == "hash":
                raise RuntimeError("cache exploded")
            super().__setattr__(name, value)

        async def aload(self) -> None:
            return None

        async def aset(self, value: ActiveFakts) -> None: ...

        async def areset(self) -> None: ...

    fakts = Fakts(
        grant=StaticGrant(), cache=ExplodingCache(), manifest=make_manifest()
    )
    with pytest.raises(RuntimeError):
        async with fakts:
            pass

    with pytest.raises(NoFaktsFound):
        get_current_fakts()


# --------------------------------------------------------------------------- #
# Manifest hashing
# --------------------------------------------------------------------------- #


async def test_manifest_hash_tolerates_absent_requirements() -> None:
    """Reachable from __aenter__, so this used to crash at startup."""
    Manifest(version="1", identifier="a", scopes=[], requirements=None).hash()


async def test_manifest_hash_is_order_independent() -> None:
    """Order-sensitivity would invalidate the cache and re-prompt the user
    for a manifest that did not actually change."""
    a = Manifest(
        version="1",
        identifier="app",
        scopes=["x", "y"],
        requirements=[
            Requirement(key="r1", service="s1"),
            Requirement(key="r2", service="s2"),
        ],
        public_sources=[
            PublicSource(kind="k1", url="u1"),
            PublicSource(kind="k2", url="u2"),
        ],
    )
    b = Manifest(
        version="1",
        identifier="app",
        scopes=["y", "x"],
        requirements=[
            Requirement(key="r2", service="s2"),
            Requirement(key="r1", service="s1"),
        ],
        public_sources=[
            PublicSource(kind="k2", url="u2"),
            PublicSource(kind="k1", url="u1"),
        ],
    )
    assert a.hash() == b.hash()
