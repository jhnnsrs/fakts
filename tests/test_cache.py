import datetime
import glob
import os
from pathlib import Path

import pytest

from fakts_next import Fakts
from fakts_next.cache.file import CacheFile, FileCache
from fakts_next.cache.nocache import NoCache

from fakts_next.grants.hard import HardFaktsGrant
from fakts_next.models import ActiveFakts, AuthFakt, Instance, Manifest, SelfFakt, Alias, Requirement

from .test_fakts_behavior import make_fakts_value


TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


def test_cache():
    grant = HardFaktsGrant(
        fakts=ActiveFakts(
            self=SelfFakt(deployment_name="test_deployment", alias=Alias(id="test", host="localhost", port=8000, path="/test")),
            auth=AuthFakt(
                client_id="test_client_id",
                client_secret="test_client",
                client_token="test_client_token",
                token_url="http://localhost:8000/token",
                report_url="http://localhost:8000/report",
            ),
            instances={
                "test": Instance(
                    service="test_service",
                    identifier="test_instance",
                    aliases=[
                        Alias(
                            id="test",
                            host="localhost",
                            port=8000,
                            path="/test",
                        )
                    ],
                )
            },
        )
    )

    fakts_next = Fakts(
        grant=grant,
        cache=FileCache(),
        manifest=Manifest(
            version="0.1.0",
            identifier="test_manifest",
            scopes=["openid", "profile", "email"],
            logo="http://localhost:8000/logo.png",
            requirements=[Requirement(key="test", service="test_service")],
        ),
    )

    with fakts_next:
        alias = fakts_next.get_alias("test", omit_challenge=True, omit_report=True)
        assert alias is not None


# --------------------------------------------------------------------------- #
# FileCache edge cases (isolated via tmp_path)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_filecache_roundtrip(tmp_path: Path):
    cache_file = str(tmp_path / "cache.json")
    cache = FileCache(cache_file=cache_file)
    value = make_fakts_value()

    await cache.aset(value)
    loaded = await cache.aload()

    assert loaded is not None
    assert loaded == value


@pytest.mark.asyncio
async def test_filecache_missing_file_returns_none(tmp_path: Path):
    cache = FileCache(cache_file=str(tmp_path / "does-not-exist.json"))
    assert await cache.aload() is None


@pytest.mark.asyncio
async def test_filecache_hash_mismatch_invalidates(tmp_path: Path):
    cache_file = str(tmp_path / "cache.json")
    await FileCache(cache_file=cache_file, hash="v1").aset(make_fakts_value())

    # A different hash means the cached config is for a different app/config.
    assert await FileCache(cache_file=cache_file, hash="v2").aload() is None
    # Same hash still loads.
    assert await FileCache(cache_file=cache_file, hash="v1").aload() is not None


@pytest.mark.asyncio
async def test_filecache_expiry_returns_none(tmp_path: Path):
    cache_file = str(tmp_path / "cache.json")
    # Hand-write a cache file created well in the past.
    stale = CacheFile(
        fakts=make_fakts_value(),
        created=datetime.datetime.now() - datetime.timedelta(seconds=3600),
        hash="",
    )
    Path(cache_file).write_text(stale.model_dump_json())

    cache = FileCache(cache_file=cache_file, expires_in=60)
    assert await cache.aload() is None


@pytest.mark.asyncio
async def test_filecache_corrupt_file_returns_none(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text("{ this is not valid json")

    cache = FileCache(cache_file=str(cache_file))
    # Corrupt cache must be treated as a miss, never raise.
    assert await cache.aload() is None


@pytest.mark.asyncio
async def test_filecache_invalid_schema_returns_none(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text('{"unexpected": "shape"}')

    cache = FileCache(cache_file=str(cache_file))
    assert await cache.aload() is None


@pytest.mark.asyncio
async def test_filecache_areset_removes_file(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    cache = FileCache(cache_file=str(cache_file))
    await cache.aset(make_fakts_value())
    assert cache_file.exists()

    await cache.areset()
    assert not cache_file.exists()
    # Resetting again on a missing file must not raise.
    await cache.areset()


@pytest.mark.asyncio
async def test_filecache_aset_is_atomic_no_tmp_left(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    cache = FileCache(cache_file=str(cache_file))
    await cache.aset(make_fakts_value())

    leftover = glob.glob(str(tmp_path / "*.tmp"))
    assert leftover == [], "Atomic write must not leave a temp file behind"


# --------------------------------------------------------------------------- #
# NoCache
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_nocache_never_persists():
    cache = NoCache()
    assert await cache.aload() is None
    # set / reset are no-ops and must not raise
    await cache.aset(make_fakts_value())
    await cache.areset()
    assert await cache.aload() is None
