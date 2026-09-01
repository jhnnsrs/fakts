"""Tests for the core Fakts behavior: single-flight loading, alias caching
and self-healing of stale caches."""

import asyncio
import os
from pathlib import Path
from typing import Optional

import pytest
from pydantic import BaseModel

from fakts_next import Fakts
from fakts_next.cache.file import FileCache
from fakts_next.errors import AliasNotFoundError, ServiceNotGrantedError
from fakts_next.fakts import Fakts as FaktsClass
from fakts_next.models import (
    ActiveFakts,
    Alias,
    AuthFakt,
    GrantStatus,
    Instance,
    Manifest,
    Requirement,
    SelfFakt,
)

pytestmark = pytest.mark.asyncio


def make_fakts_value(
    host: str = "localhost",
    *,
    refresh_token: str = "test_refresh_token",
    client_id: str = "test_client_id",
    access_token: str | None = None,
    expires_at: float | None = None,
) -> ActiveFakts:
    return ActiveFakts(
        self=SelfFakt(
            deployment_name="test_deployment",
            alias=Alias(id="self", host=host, port=8000, path="/self"),
        ),
        auth=AuthFakt(
            client_id=client_id,
            refresh_token=refresh_token,
            access_token=access_token,
            expires_at=expires_at,
            token_endpoint=f"http://{host}:8000/token",
            report_endpoint=f"http://{host}:8000/report",
        ),
        instances={
            "test": Instance(
                service="test_service",
                identifier="test_instance",
                aliases=[
                    Alias(id="primary", host=host, port=8000, path="/test"),
                    Alias(id="fallback", host=host, port=8001, path="/test"),
                ],
            )
        },
    )


def make_manifest() -> Manifest:
    return Manifest(
        version="0.1.0",
        identifier="test_manifest",
        scopes=["openid"],
        requirements=[Requirement(key="test", service="test_service")],
    )


class CountingGrant(BaseModel):
    """A grant that counts how often it was loaded"""

    fakts: ActiveFakts
    load_count: int = 0
    delay: float = 0

    async def aload(self) -> ActiveFakts:
        self.load_count += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.fakts


class MemoryCache(BaseModel):
    """An in-memory cache that counts sets and can be preseeded"""

    value: Optional[ActiveFakts] = None
    hash: str = ""
    set_count: int = 0

    async def aload(self) -> Optional[ActiveFakts]:
        return self.value

    async def aset(self, value: ActiveFakts) -> None:
        self.value = value
        self.set_count += 1

    async def areset(self) -> None:
        self.value = None


class FailingSetCache(BaseModel):
    """A cache whose writes always fail (e.g. read-only file system)"""

    value: Optional[ActiveFakts] = None
    hash: str = ""

    async def aload(self) -> Optional[ActiveFakts]:
        return self.value

    async def aset(self, value: ActiveFakts) -> None:
        raise OSError("read-only file system")

    async def areset(self) -> None:
        self.value = None


async def test_concurrent_first_access_loads_grant_once():
    """Concurrent consumers must not trigger the (interactive) grant twice."""
    grant = CountingGrant(fakts=make_fakts_value(), delay=0.05)
    fakts = Fakts(grant=grant, manifest=make_manifest())

    async with fakts:
        results = await asyncio.gather(
            fakts.aload(),
            fakts.aload(),
            fakts.aget_alias("test", omit_challenge=True, omit_report=True),
            fakts.aget_alias("test", omit_challenge=True, omit_report=True),
        )

    assert grant.load_count == 1
    assert results[2].id == "primary"


async def test_alias_is_cached_after_first_resolution(monkeypatch: pytest.MonkeyPatch):
    """After the first full resolution, getting an alias must not challenge again."""
    challenge_count = 0

    async def fake_challenge(self: FaktsClass, alias: Alias, challenge_key: object = None) -> bool:
        nonlocal challenge_count
        challenge_count += 1
        return True

    monkeypatch.setattr(FaktsClass, "achallenge_alias", fake_challenge)

    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(grant=grant, manifest=make_manifest())

    async with fakts:
        first = await fakts.aget_alias("test", omit_report=True)
        challenges_after_first = challenge_count

        second = await fakts.aget_alias("test", omit_report=True)
        third = await fakts.aget_alias("test", omit_report=True)

    assert first.id == second.id == third.id == "primary"
    assert challenge_count == challenges_after_first, (
        "Subsequent gets must use the cached alias without re-challenging"
    )


async def test_last_used_alias_is_moved_to_front_and_persisted(
    monkeypatch: pytest.MonkeyPatch,
):
    """If a fallback alias is selected, it becomes the preferred alias in the cache."""

    async def fake_challenge(self: FaktsClass, alias: Alias, challenge_key: object = None) -> bool:
        if alias.id == "primary":
            raise Exception("unreachable")
        return True

    monkeypatch.setattr(FaktsClass, "achallenge_alias", fake_challenge)

    grant = CountingGrant(fakts=make_fakts_value())
    cache = MemoryCache()
    fakts = Fakts(grant=grant, cache=cache, manifest=make_manifest())

    async with fakts:
        alias = await fakts.aget_alias("test", omit_report=True)

    assert alias.id == "fallback"
    assert cache.value is not None
    assert cache.value.instances["test"].aliases[0].id == "fallback", (
        "The selected alias should be persisted as the preferred one"
    )


async def test_stale_cache_self_heals(monkeypatch: pytest.MonkeyPatch):
    """If aliases from cached fakts fail, the fakts are reloaded from the grant."""

    async def fake_challenge(self: FaktsClass, alias: Alias, challenge_key: object = None) -> bool:
        if alias.host == "stale-host":
            raise Exception("unreachable")
        return True

    monkeypatch.setattr(FaktsClass, "achallenge_alias", fake_challenge)

    grant = CountingGrant(fakts=make_fakts_value())
    cache = MemoryCache(value=make_fakts_value(host="stale-host"), hash="static")
    fakts = Fakts(grant=grant, cache=cache, manifest=make_manifest())

    async with fakts:
        alias = await fakts.aget_alias("test", omit_report=True)

    assert alias.host == "localhost"
    assert grant.load_count == 1, "The stale cache should have been reloaded once"


async def test_optional_missing_service_does_not_refresh_every_time():
    """A missing optional service raises, but must not re-resolve on every get."""
    manifest = make_manifest()
    assert manifest.requirements is not None
    manifest.requirements.append(
        Requirement(key="missing", service="missing_service", optional=True)
    )

    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(grant=grant, manifest=manifest)

    async with fakts:
        await fakts.aget_alias("test", omit_challenge=True, omit_report=True)

        with pytest.raises(AliasNotFoundError):
            await fakts.aget_alias("missing", omit_challenge=True, omit_report=True)
        with pytest.raises(AliasNotFoundError):
            await fakts.aget_alias("missing", omit_challenge=True, omit_report=True)

    assert grant.load_count == 1


async def test_optional_not_granted_raises_service_not_granted():
    """A declared optional service without a granted instance must raise
    ServiceNotGrantedError, so callers can degrade gracefully."""
    manifest = make_manifest()
    assert manifest.requirements is not None
    manifest.requirements.append(
        Requirement(key="declined", service="declined_service", optional=True)
    )

    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(grant=grant, manifest=manifest)

    async with fakts:
        with pytest.raises(ServiceNotGrantedError, match="did not grant"):
            await fakts.aget_alias("declined", omit_challenge=True, omit_report=True)


async def test_undeclared_key_is_not_a_grant_problem():
    """An undeclared key is a programming error, not a declined grant."""
    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(grant=grant, manifest=make_manifest())

    async with fakts:
        with pytest.raises(AliasNotFoundError, match="Add 'undeclared'") as excinfo:
            await fakts.aget_alias("undeclared", omit_challenge=True, omit_report=True)

    assert not isinstance(excinfo.value, ServiceNotGrantedError)


async def test_unreachable_granted_service_is_not_a_grant_problem(
    monkeypatch: pytest.MonkeyPatch,
):
    """A granted but unreachable optional service must not look like a
    declined grant."""

    async def fake_challenge(self: FaktsClass, alias: Alias, challenge_key: object = None) -> bool:
        raise Exception("unreachable")

    monkeypatch.setattr(FaktsClass, "achallenge_alias", fake_challenge)

    manifest = make_manifest()
    assert manifest.requirements is not None
    manifest.requirements[0].optional = True

    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(grant=grant, manifest=manifest)

    async with fakts:
        with pytest.raises(AliasNotFoundError, match="failed their challenge") as excinfo:
            await fakts.aget_alias("test", omit_report=True)

    assert not isinstance(excinfo.value, ServiceNotGrantedError)


async def test_grant_status_explicit_derived_and_unknown():
    """Explicit server statuses win; a granted instance derives GRANTED;
    anything else is UNKNOWN."""
    value = make_fakts_value()
    value.statuses = {"declined": GrantStatus.DENIED}

    manifest = make_manifest()
    assert manifest.requirements is not None
    manifest.requirements.append(
        Requirement(key="declined", service="declined_service", optional=True)
    )
    manifest.requirements.append(
        Requirement(key="mystery", service="mystery_service", optional=True)
    )

    grant = CountingGrant(fakts=value)
    fakts = Fakts(grant=grant, manifest=manifest)

    async with fakts:
        assert await fakts.aget_grant_status("test") == GrantStatus.GRANTED
        assert await fakts.aget_grant_status("declined") == GrantStatus.DENIED
        assert await fakts.aget_grant_status("mystery") == GrantStatus.UNKNOWN
        assert await fakts.agranted("test") is True
        assert await fakts.agranted("declined") is False


async def test_explicit_status_is_reflected_in_error_message():
    """A reported denial/unavailability must show up in the error instead
    of the hedged 'may have declined' message."""
    value = make_fakts_value()
    value.statuses = {
        "declined": GrantStatus.DENIED,
        "missing": GrantStatus.UNAVAILABLE,
    }

    manifest = make_manifest()
    assert manifest.requirements is not None
    manifest.requirements.append(
        Requirement(key="declined", service="declined_service", optional=True)
    )
    manifest.requirements.append(
        Requirement(key="missing", service="missing_service", optional=True)
    )

    grant = CountingGrant(fakts=value)
    fakts = Fakts(grant=grant, manifest=manifest)

    async with fakts:
        with pytest.raises(ServiceNotGrantedError, match="user declined access"):
            await fakts.aget_alias("declined", omit_challenge=True, omit_report=True)
        with pytest.raises(ServiceNotGrantedError, match="does not offer"):
            await fakts.aget_alias("missing", omit_challenge=True, omit_report=True)


async def test_unknown_status_values_are_coerced():
    """A status value from a newer server must not break validation."""
    raw = make_fakts_value().model_dump()
    raw["statuses"] = {"test": "revoked", "other": "denied"}

    parsed = ActiveFakts.model_validate(raw)

    assert parsed.statuses["test"] == GrantStatus.UNKNOWN
    assert parsed.statuses["other"] == GrantStatus.DENIED


async def test_aget_alias_or_none():
    """Not-granted and unreachable services yield None; undeclared keys
    still raise (a bug, not a runtime condition)."""
    manifest = make_manifest()
    assert manifest.requirements is not None
    manifest.requirements.append(
        Requirement(key="declined", service="declined_service", optional=True)
    )

    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(grant=grant, manifest=manifest)

    async with fakts:
        alias = await fakts.aget_alias_or_none(
            "test", omit_challenge=True, omit_report=True
        )
        assert alias is not None and alias.id == "primary"

        assert (
            await fakts.aget_alias_or_none(
                "declined", omit_challenge=True, omit_report=True
            )
            is None
        )

        with pytest.raises(AliasNotFoundError, match="Add 'undeclared'"):
            await fakts.aget_alias_or_none("undeclared", omit_challenge=True)


async def test_report_skipped_when_endpoint_has_no_report_url():
    """With reporting on (the default), a missing report_url must be skipped silently."""
    value = make_fakts_value()
    value.auth.report_endpoint = None

    grant = CountingGrant(fakts=value)
    fakts = Fakts(grant=grant, manifest=make_manifest())

    async with fakts:
        alias = await fakts.aget_alias("test", omit_challenge=True)

    assert alias.id == "primary"


async def test_report_errors_are_caught():
    """A failing report endpoint must log and continue, not break alias resolution."""
    value = make_fakts_value(access_token="cached_access_token")
    value.auth.report_endpoint = "http://localhost:1/report"

    grant = CountingGrant(fakts=value)
    fakts = Fakts(grant=grant, manifest=make_manifest())

    async with fakts:
        alias = await fakts.aget_alias("test", omit_challenge=True)

    assert alias.id == "primary"


async def test_manifest_hash_invalidates_cache(tmp_path: Path):
    """Changing the manifest must invalidate the cached fakts."""
    cache_file = str(tmp_path / "cache.json")

    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(
        grant=grant, cache=FileCache(cache_file=cache_file), manifest=make_manifest()
    )
    async with fakts:
        await fakts.aload()
    assert grant.load_count == 1

    # Same manifest: the cache is reused
    fakts = Fakts(
        grant=grant, cache=FileCache(cache_file=cache_file), manifest=make_manifest()
    )
    async with fakts:
        await fakts.aload()
    assert grant.load_count == 1

    # Changed manifest: the cache is invalidated
    changed = make_manifest()
    changed.scopes = ["openid", "profile"]
    fakts = Fakts(grant=grant, cache=FileCache(cache_file=cache_file), manifest=changed)
    async with fakts:
        await fakts.aload()
    assert grant.load_count == 2


async def test_corrupt_cache_file_is_ignored(tmp_path: Path):
    """A corrupt cache file must not break startup."""
    cache_file = str(tmp_path / "cache.json")
    with open(cache_file, "w") as f:
        f.write("{not valid json")

    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(
        grant=grant, cache=FileCache(cache_file=cache_file), manifest=make_manifest()
    )
    async with fakts:
        loaded = await fakts.aload()

    assert loaded == make_fakts_value()
    assert grant.load_count == 1


async def test_arefresh_reloads_from_grant():
    """arefresh must bypass cache and loaded fakts (used to raise AttributeError)."""
    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(grant=grant, manifest=make_manifest())

    async with fakts:
        await fakts.aload()
        await fakts.arefresh()

    assert grant.load_count == 2


async def test_entering_does_not_run_the_grant():
    """Entering the context is pure setup: locks and the cache hash binding.

    There used to be a `load_on_enter` flag that ran the grant here. It made
    `async with fakts:` able to open a browser and to fail with whatever the
    grant failed with, at a place where callers expect neither. Loading is
    lazy (allow_auto_load) or explicit.
    """
    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(grant=grant, manifest=make_manifest())

    async with fakts:
        assert grant.load_count == 0
        assert fakts.loaded_fakts is None

        # ...and it still loads on first use.
        await fakts.aload()
        assert grant.load_count == 1
        assert fakts.loaded_fakts is not None


async def test_cache_write_failure_is_not_fatal(monkeypatch: pytest.MonkeyPatch):
    """A failing cache write must not break loading or alias resolution."""

    async def fake_challenge(self: FaktsClass, alias: Alias, challenge_key: object = None) -> bool:
        if alias.id == "primary":
            raise Exception("unreachable")
        return True

    monkeypatch.setattr(FaktsClass, "achallenge_alias", fake_challenge)

    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(grant=grant, cache=FailingSetCache(), manifest=make_manifest())

    async with fakts:
        loaded = await fakts.aload()
        assert loaded == make_fakts_value()
        # Selecting the fallback alias triggers the second (alias reorder)
        # cache write, which must also be non-fatal.
        alias = await fakts.aget_alias("test", omit_report=True)

    assert alias.id == "fallback"
    assert grant.load_count == 1


async def test_rejected_credential_adopts_fresh_cached_one():
    """If the cache holds a credential we have not tried (e.g. a sibling
    process rotated first), adopt it instead of re-running the grant."""
    fresh = make_fakts_value(refresh_token="rotated_token", client_id="new_client_id")

    grant = CountingGrant(fakts=make_fakts_value())
    cache = MemoryCache(value=fresh)
    fakts = Fakts(grant=grant, cache=cache, manifest=make_manifest())

    async with fakts:
        adopted = await fakts._aadopt_cached_credentials(set())

        assert adopted is not None
        assert fakts.loaded_fakts is not None
        assert fakts.loaded_fakts.auth.client_id == "new_client_id"
        assert fakts.loaded_fakts.auth.refresh_token == "rotated_token"
        assert grant.load_count == 0, "The grant must not have been triggered"


async def test_already_tried_credential_is_not_adopted_again():
    """Adoption keys on (client_id, refresh_token). Re-adopting something we
    already tried would spin instead of converging."""
    cached = make_fakts_value(refresh_token="tok_a", client_id="cid_a")

    grant = CountingGrant(fakts=make_fakts_value())
    cache = MemoryCache(value=cached)
    fakts = Fakts(grant=grant, cache=cache, manifest=make_manifest())

    async with fakts:
        adopted = await fakts._aadopt_cached_credentials({("cid_a", "tok_a")})

    assert adopted is None


async def test_reapproval_rotating_client_id_is_adopted():
    """Re-approval rotates the client identity too, so a matching refresh
    token alone must not be treated as 'the same credential'."""
    cached = make_fakts_value(refresh_token="same_token", client_id="rotated_client")

    grant = CountingGrant(fakts=make_fakts_value())
    cache = MemoryCache(value=cached)
    fakts = Fakts(grant=grant, cache=cache, manifest=make_manifest())

    async with fakts:
        adopted = await fakts._aadopt_cached_credentials({("old_client", "same_token")})

    assert adopted is not None
    assert adopted.auth.client_id == "rotated_client"


async def test_delete_on_exit(tmp_path: Path):
    cache_file = str(tmp_path / "cache.json")
    grant = CountingGrant(fakts=make_fakts_value())
    fakts = Fakts(
        grant=grant,
        cache=FileCache(cache_file=cache_file),
        manifest=make_manifest(),
        delete_on_exit=True,
    )

    async with fakts:
        await fakts.aload()
        assert os.path.exists(cache_file)

    assert not os.path.exists(cache_file)
    assert fakts.loaded_fakts is None
