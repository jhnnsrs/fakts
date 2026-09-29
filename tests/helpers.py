"""Shared test helpers: configurations, grants and caches the suites build on.

Plain functions and classes, importable from any test module. Fixtures live in
conftest.py.
"""

import asyncio
import socket
import time

from pydantic import BaseModel

from fakts.models import (
    ActiveFakts,
    Alias,
    AuthFakt,
    Instance,
    Manifest,
    Requirement,
    SelfFakt,
)


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
    requires_user_interaction: bool = True

    async def aload(self) -> ActiveFakts:
        self.load_count += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.fakts


class StaticGrant(BaseModel):
    """A grant that hands back a fixed configuration."""

    fakts: ActiveFakts
    load_count: int = 0
    requires_user_interaction: bool = True

    async def aload(self) -> ActiveFakts:
        self.load_count += 1
        return self.fakts


class MemoryCache(BaseModel):
    """An in-memory cache that stores a deep copy, as a real cache would."""

    value: ActiveFakts | None = None
    hash: str = ""
    set_count: int = 0

    async def aload(self) -> ActiveFakts | None:
        return self.value

    async def aset(self, value: ActiveFakts) -> None:
        self.value = value.model_copy(deep=True)
        self.set_count += 1

    async def areset(self) -> None:
        self.value = None


def token_body(access: str, refresh: str, expires_in: int = 3600) -> dict:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": "openid",
        "client_id": "test_client_id",
        "self": {
            "deployment_name": "test_deployment",
            "alias": {"id": "self", "host": "localhost", "port": 8000, "path": "/self"},
        },
        "instances": {
            "test": {
                "service": "test_service",
                "identifier": "1",
                "aliases": [
                    {"id": "primary", "host": "localhost", "port": 8000, "path": "/test"},
                    {"id": "fallback", "host": "localhost", "port": 8001, "path": "/test"},
                ],
            }
        },
        "statuses": {"test": "granted"},
    }


def fakts_pointing_at(token_endpoint: str, **kwargs) -> ActiveFakts:
    value = make_fakts_value(**kwargs)
    value.auth.token_endpoint = token_endpoint
    value.auth.refresh_issued_at = time.time()
    value.auth.chain_started_at = time.time()
    return value


def reserve_free_ports(count: int) -> list[int]:
    """Ask the OS for `count` distinct free TCP ports.

    All sockets are held open until every port has been assigned, so the
    kernel cannot hand out the same port twice within one call. They are
    released before compose binds them -- a race in theory, but the ephemeral
    range is large and this is what keeps concurrent runs (and the leftovers
    of a crashed one) from colliding on a fixed port.
    """
    sockets: list[socket.socket] = []
    try:
        for _ in range(count):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [int(sock.getsockname()[1]) for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()
