"""Tests for the EnvGrant and the Fakts-level convenience builders."""

from pathlib import Path

import pytest

from fakts import (
    EnvGrant,
    Fakts,
    FileCache,
    GrantError,
    NoCache,
    build_device_code_fakts,
    build_redeem_fakts,
)
from fakts.grants.remote.authorizers.device_code import DeviceCodeAuthorizer
from fakts.grants.remote.authorizers.redeem import RedeemAuthorizer

from .test_fakts_behavior import make_fakts_value, make_manifest

pytestmark = pytest.mark.asyncio


async def test_env_grant_inline_json(monkeypatch: pytest.MonkeyPatch):
    value = make_fakts_value()
    monkeypatch.setenv("FAKTS", value.model_dump_json())

    fakts = Fakts(grant=EnvGrant(), manifest=make_manifest())
    async with fakts:
        loaded = await fakts.aload()

    assert loaded == value


async def test_env_grant_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    value = make_fakts_value()
    config_file = tmp_path / "fakts.json"
    config_file.write_text(value.model_dump_json())

    monkeypatch.delenv("FAKTS", raising=False)
    monkeypatch.setenv("FAKTS_FILE", str(config_file))

    fakts = Fakts(grant=EnvGrant(), manifest=make_manifest())
    async with fakts:
        loaded = await fakts.aload()

    assert loaded == value


async def test_env_grant_errors_are_verbose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("FAKTS", raising=False)
    monkeypatch.delenv("FAKTS_FILE", raising=False)

    grant = EnvGrant()

    with pytest.raises(GrantError, match=r"\$FAKTS.*\$FAKTS_FILE"):
        await grant.aload()

    monkeypatch.setenv("FAKTS", "{not valid json")
    with pytest.raises(GrantError, match=r"(?s)\$FAKTS is set.*json_invalid"):
        await grant.aload()

    monkeypatch.delenv("FAKTS")
    monkeypatch.setenv("FAKTS_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(GrantError, match=r"missing\.json.*does not exist"):
        await grant.aload()


async def test_env_grant_errors_never_echo_the_credential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A malformed FAKTS blob must not put the refresh token in the error.

    This is the whole failure mode: no attacker is involved, just a typo in a
    deployment, and the traceback goes wherever logs go.
    """
    import json

    secret = "v1.SUPERSECRET_REFRESH_TOKEN_ABCDEFGHIJKLMNOP"
    broken = json.dumps(
        {
            "self": {"deployment_name": "d", "alias": {"id": "a", "host": "h"}},
            "auth": {"client_id": "CID", "refresh_token": secret},  # no token_endpoint
        }
    )

    grant = EnvGrant()

    monkeypatch.delenv("FAKTS_FILE", raising=False)
    monkeypatch.setenv("FAKTS", broken)
    with pytest.raises(GrantError) as inline:
        await grant.aload()
    assert secret not in str(inline.value)
    assert "token_endpoint" in str(inline.value), "the error must still be actionable"

    monkeypatch.delenv("FAKTS")
    path = tmp_path / "fakts.json"
    path.write_text(broken)
    monkeypatch.setenv("FAKTS_FILE", str(path))
    with pytest.raises(GrantError) as from_file:
        await grant.aload()
    assert secret not in str(from_file.value)


async def test_build_device_code_fakts_wiring(tmp_path: Path):
    manifest = make_manifest()
    fakts = build_device_code_fakts(
        url="http://localhost:8000",
        manifest=manifest,
        cache_file=str(tmp_path / "cache.json"),
        headless=True,
    )

    assert isinstance(fakts.grant.authorizer, DeviceCodeAuthorizer)
    assert fakts.grant.authorizer.manifest is manifest
    assert fakts.manifest is manifest
    assert fakts.grant.authorizer.open_browser is False
    assert isinstance(fakts.cache, FileCache)
    assert fakts.cache.hash, (
        "The builder should bind a hash so manifest/server changes invalidate the cache"
    )


async def test_builder_cache_hash_binds_url_and_manifest(tmp_path: Path):
    """The cache must be invalidated when either the manifest or the server
    url changes — otherwise a different server is served the cached fakts
    of the old one."""

    def build(url: str, manifest) -> Fakts:
        return build_device_code_fakts(
            url=url,
            manifest=manifest,
            cache_file=str(tmp_path / "cache.json"),
            headless=True,
        )

    manifest = make_manifest()
    base = build("http://localhost:8000", manifest)
    same = build("http://localhost:8000", make_manifest())
    other_url = build("http://otherhost:8000", manifest)

    changed_manifest = make_manifest()
    changed_manifest.scopes = ["openid", "profile"]
    other_manifest = build("http://localhost:8000", changed_manifest)

    assert base.cache.hash == same.cache.hash
    assert base.cache.hash != other_url.cache.hash
    assert base.cache.hash != other_manifest.cache.hash


async def test_build_redeem_fakts_wiring():
    manifest = make_manifest()
    fakts = build_redeem_fakts(
        url="http://localhost:8000",
        manifest=manifest,
        token="redeem-me",
        no_cache=True,
    )

    assert isinstance(fakts.grant.authorizer, RedeemAuthorizer)
    assert fakts.grant.authorizer.token == "redeem-me"
    assert isinstance(fakts.cache, NoCache)
