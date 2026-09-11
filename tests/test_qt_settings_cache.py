"""Tests for the QtSettingsCache (hash validation and expiry)."""

import datetime
from pathlib import Path

import pytest

pytest.importorskip("qtpy")

from qtpy import QtCore

from fakts_next.cache.model import CacheModel
from fakts_next.cache.qt.settings import QtSettingsCache

from .test_fakts_behavior import make_fakts_value

pytestmark = pytest.mark.asyncio


def make_settings(tmp_path: Path) -> QtCore.QSettings:
    return QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
    )


async def test_qt_cache_roundtrip(tmp_path: Path):
    cache = QtSettingsCache(settings=make_settings(tmp_path))
    value = make_fakts_value()

    await cache.aset(value)
    assert await cache.aload() == value

    await cache.areset()
    assert await cache.aload() is None


async def test_qt_cache_hash_mismatch_is_a_miss(tmp_path: Path):
    settings = make_settings(tmp_path)
    value = make_fakts_value()

    await QtSettingsCache(settings=settings, hash="old").aset(value)
    assert await QtSettingsCache(settings=settings, hash="new").aload() is None


async def test_qt_cache_expires(tmp_path: Path):
    settings = make_settings(tmp_path)
    cache = QtSettingsCache(settings=settings, expires_in=3600)
    value = make_fakts_value()

    await cache.aset(value)
    assert await cache.aload() == value, "A fresh cache must not be expired"

    stale = CacheModel(
        config=value.model_dump(),
        created=datetime.datetime.now() - datetime.timedelta(seconds=7200),
        hash="",
    )
    settings.setValue(cache.save_key, stale.model_dump_json())
    assert await cache.aload() is None, "An expired cache must be a miss"
