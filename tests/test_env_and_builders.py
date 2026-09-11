"""Tests for the EnvGrant and the Fakts-level convenience builders."""

from pathlib import Path

import pytest

from fakts_next import (
    EnvGrant,
    Fakts,
    FileCache,
    GrantError,
    NoCache,
    build_device_code_fakts,
    build_redeem_fakts,
)
from fakts_next.grants.remote.demanders.device_code import DeviceCodeDemander
from fakts_next.grants.remote.demanders.redeem import RedeemDemander

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
    with pytest.raises(GrantError, match=r"(?s)\$FAKTS is set.*not valid json"):
        await grant.aload()

    monkeypatch.delenv("FAKTS")
    monkeypatch.setenv("FAKTS_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(GrantError, match=r"missing\.json.*does not exist"):
        await grant.aload()


async def test_build_device_code_fakts_wiring(tmp_path: Path):
    manifest = make_manifest()
    fakts = build_device_code_fakts(
        url="http://localhost:8000",
        manifest=manifest,
        cache_file=str(tmp_path / "cache.json"),
        headless=True,
    )

    assert isinstance(fakts.grant.demander, DeviceCodeDemander)
    assert fakts.grant.demander.manifest is manifest
    assert fakts.manifest is manifest
    assert fakts.grant.demander.open_browser is False
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

    assert isinstance(fakts.grant.demander, RedeemDemander)
    assert fakts.grant.demander.token == "redeem-me"
    assert isinstance(fakts.cache, NoCache)
