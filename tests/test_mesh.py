"""The mesh: aliases only reachable over the deployment's tailnet, reached
through the in-process mesh node's HTTP proxy (or a running one).

``arkitekt_mesh`` is faked here; the real bindings are tested against a
tailnet in arkirust's ``crates/mesh-py``, and by ``test_a_real_node`` below
when a lab mesh is configured.
"""

import os
import sys
from pathlib import Path
from typing import Any, List

import pytest
import pytest_asyncio
from aiohttp import web

from fakts import Fakts
from fakts.grants.remote.authorizers.device_code import DeviceCodeAuthorizer
from fakts.grants.remote.models import FaktsEndpoint
from fakts.mesh import MeshError, MeshOptions, NativeNode, hostname_label
from fakts.models import ActiveFakts, Alias, Instance, MeshClaim, SelfFakt
from fakts.oauth2 import TokenResponse, merge_token_response

from .test_fakts_behavior import CountingGrant, make_fakts_value, make_manifest


def test_hostnames_are_dns_labels() -> None:
    assert hostname_label("My App_v2") == "my-app-v2"
    assert hostname_label("--x--") == "x"
    assert hostname_label("!!!") == "arkitekt-app"
    assert len(hostname_label("a" * 80)) == 63


def test_nodes_live_in_the_native_directory(tmp_path: Path) -> None:
    # The Rust client's native backend names its node directories the same way.
    assert (
        MeshOptions(state_root=tmp_path).node_dir("app-x") == tmp_path / "app-x-native"
    )


def test_self_ids_may_be_numbers() -> None:
    me = SelfFakt.model_validate(
        {
            "deployment_name": "d",
            "alias": {"id": "s", "host": "h"},
            "sub": 1,
            "organization": 2,
            "hub": "3",
        }
    )
    assert (me.sub, me.organization, me.hub) == ("1", "2", "3")


@pytest.mark.asyncio
async def test_the_mesh_key_is_only_requested_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: List[dict] = []

    async def capture(url: str, payload: dict, **kwargs: Any) -> dict:
        sent.append(payload)
        return {}

    monkeypatch.setattr(
        "fakts.grants.remote.authorizers.device_code.oauth2.apost_json", capture
    )
    endpoint = FaktsEndpoint(device_authorization_endpoint="http://localhost/device")
    await DeviceCodeAuthorizer(manifest=make_manifest()).arequest_code(endpoint)
    await DeviceCodeAuthorizer(
        manifest=make_manifest(), request_auth_key=True
    ).arequest_code(endpoint)
    assert "request_auth_key" not in sent[0]
    assert sent[1]["request_auth_key"] is True


def test_the_mesh_key_survives_refreshes() -> None:
    first = merge_token_response(
        None,
        TokenResponse.model_validate(
            {
                "access_token": "a1",
                "refresh_token": "r1",
                "client_id": "c",
                "self": {"deployment_name": "d", "alias": {"id": "s", "host": "h"}},
                "mesh": {
                    "ionscale_auth_key": "mesh-key",
                    "ionscale_coord_url": "https://mesh.test",
                },
            }
        ),
        token_endpoint="http://h/token",
        report_endpoint=None,
        skew=0,
    )
    assert first.mesh == MeshClaim(
        ionscale_auth_key="mesh-key", ionscale_coord_url="https://mesh.test"
    )
    # Only the first token carries it.
    refreshed = merge_token_response(
        first,
        TokenResponse(access_token="a2", refresh_token="r2", client_id="c"),
        token_endpoint="http://h/token",
        report_endpoint=None,
        skew=0,
    )
    assert refreshed.mesh == first.mesh
    # And it is cached with the rest.
    assert (
        ActiveFakts.model_validate_json(refreshed.model_dump_json()).mesh == first.mesh
    )


# --- resolution ------------------------------------------------------------


def mesh_fakts() -> ActiveFakts:
    """One instance: a mesh alias first, a direct fallback second."""
    value = make_fakts_value()
    value.auth.report_endpoint = None
    value.instances["test"] = Instance(
        service="test_service",
        identifier="test_instance",
        aliases=[
            Alias(
                id="mesh",
                host="100.64.0.9",
                port=8080,
                path="/test",
                challenge="ht",
                kind="mesh",
            ),
            Alias(id="direct", host="localhost", port=1, path="/test", challenge="ht"),
        ],
    )
    return value


@pytest_asyncio.fixture
async def mesh_proxy() -> Any:
    """A forward proxy that answers every challenge and records the request lines."""
    seen: List[str] = []

    async def handle(request: web.Request) -> web.Response:
        seen.append(f"{request.method} {request.url}")
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    yield f"http://127.0.0.1:{port}", seen
    await runner.cleanup()


@pytest.mark.asyncio
async def test_mesh_aliases_are_challenged_through_the_proxy(mesh_proxy: Any) -> None:
    proxy, seen = mesh_proxy
    fakts = Fakts(
        grant=CountingGrant(fakts=mesh_fakts()),
        manifest=make_manifest(),
        mesh_proxy=proxy,
    )
    async with fakts:
        alias = await fakts.aget_alias("test")
        assert alias.id == "mesh"
        assert alias.proxy == proxy
        assert seen == ["GET http://100.64.0.9:8080/test/ht"]
        # Served from the alias map, still carrying the proxy.
        again = await fakts.aget_alias("test")
        assert again.proxy == proxy
        # The instance (what gets cached) never holds it.
        assert fakts.loaded_fakts is not None
        assert all(
            a.proxy is None for a in fakts.loaded_fakts.instances["test"].aliases
        )


@pytest.mark.asyncio
async def test_mesh_aliases_are_skipped_without_the_mesh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    challenged: List[str] = []

    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None) -> bool:
        challenged.append(alias.id)
        return True

    monkeypatch.setattr(Fakts, "achallenge_alias", challenge)
    fakts = Fakts(grant=CountingGrant(fakts=mesh_fakts()), manifest=make_manifest())
    async with fakts:
        alias = await fakts.aget_alias("test")
    assert alias.id == "direct"
    assert alias.proxy is None
    assert challenged == ["direct"]


# --- the native backend (arkitekt_mesh, faked here; the real one is tested
# against a tailnet in arkirust's crates/mesh-py) ---------------------------


class FakeNode:
    started: List[dict] = []

    def __init__(self, statedir: str, proxy_url: str):
        self.statedir = statedir
        self.proxy_url = proxy_url
        self.closed = False
        self.forwards: List[tuple] = []

    @staticmethod
    async def start(statedir, hostname, control_url=None, auth_key=None, timeout=90):
        FakeNode.started.append(
            {
                "statedir": statedir,
                "hostname": hostname,
                "control_url": control_url,
                "auth_key": auth_key,
            }
        )
        if auth_key is None:
            raise FakeNeedsLogin("no key")
        return FakeNode(statedir, FakeNode.proxy)

    @staticmethod
    def has_state(statedir):
        return False

    async def turn(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            urls=["turn:127.0.0.1:3478?transport=udp"], username="u", credential="c"
        )

    async def forward(self, host, port):
        self.forwards.append((host, port))
        return "127.0.0.1:5555"

    def close(self):
        self.closed = True


class FakeMeshError(Exception):
    pass


class FakeNeedsLogin(FakeMeshError):
    pass


class FakeLocked(FakeMeshError):
    pass


class FakeRefused(FakeMeshError):
    pass


class FakeTimeout(FakeMeshError):
    pass


class FakeLockedOut(FakeMeshError):
    pass


@pytest.fixture
def fake_arkitekt_mesh(monkeypatch: pytest.MonkeyPatch):
    import types

    module = types.ModuleType("arkitekt_mesh")
    module.Node = FakeNode  # type: ignore[attr-defined]
    module.MeshError = FakeMeshError  # type: ignore[attr-defined]
    module.NeedsLogin = FakeNeedsLogin  # type: ignore[attr-defined]
    module.Locked = FakeLocked  # type: ignore[attr-defined]
    module.Refused = FakeRefused  # type: ignore[attr-defined]
    module.Timeout = FakeTimeout  # type: ignore[attr-defined]
    module.LockedOut = FakeLockedOut  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "arkitekt_mesh", module)
    FakeNode.started = []
    return module


@pytest.mark.asyncio
async def test_fakts_runs_the_native_node(
    fake_arkitekt_mesh: Any, tmp_path: Path, mesh_proxy: Any
) -> None:
    proxy, seen = mesh_proxy
    FakeNode.proxy = proxy  # type: ignore[attr-defined]
    value = mesh_fakts()
    value.mesh = MeshClaim(
        ionscale_auth_key="tskey-secret", ionscale_coord_url="https://mesh.example"
    )
    fakts = Fakts(
        grant=CountingGrant(fakts=value),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=tmp_path, timeout=10),
    )
    async with fakts:
        alias = await fakts.aget_alias("test")
        assert alias.id == "mesh" and alias.proxy == proxy
        assert seen == ["GET http://100.64.0.9:8080/test/ht"]
        start = FakeNode.started[0]
        assert start["auth_key"] == "tskey-secret"
        assert start["control_url"] == "https://mesh.example"
        assert start["statedir"].endswith("-native")

        turn = await fakts.amesh_turn()
        assert turn.urls == ["turn:127.0.0.1:3478?transport=udp"]
        assert turn.username == "u" and turn.credential == "c"
        assert await fakts.amesh_forward(alias) == "127.0.0.1:5555"
        assert await fakts.amesh_forward(alias, 7880) == "127.0.0.1:5555"
        node = fakts._mesh_node
        assert node is not None and node._node.forwards == [
            ("100.64.0.9", 8080),
            ("100.64.0.9", 7880),
        ]
    assert node._node.closed


@pytest.mark.asyncio
async def test_native_needs_login_is_a_mesh_error(
    fake_arkitekt_mesh: Any, tmp_path: Path
) -> None:
    with pytest.raises(MeshError, match="no mesh key was granted") as raised:
        await NativeNode.start(
            MeshOptions(), tmp_path / "n", "app", "https://mesh.example", None
        )
    assert raised.value.code == "needs_login"


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (FakeLocked("busy"), "locked", "already running in"),
        (FakeRefused("bad key"), "login", "refused this node: bad key"),
        (FakeTimeout("90s"), "timeout", "did not connect in time"),
        (FakeLockedOut("sign nodekey:abc"), "locked_out", "nodekey:abc"),
        (FakeMeshError("boom"), "start", "boom"),
    ],
)
@pytest.mark.asyncio
async def test_node_errors_keep_their_code(
    fake_arkitekt_mesh: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: Exception,
    code: str,
    message: str,
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(FakeNode, "start", staticmethod(fail))
    with pytest.raises(MeshError, match=message) as raised:
        await NativeNode.start(
            MeshOptions(), tmp_path / "n", "app", "https://mesh.example", "key"
        )
    assert raised.value.code == code


@pytest.mark.asyncio
async def test_missing_bindings_say_what_to_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "arkitekt_mesh", None)
    with pytest.raises(MeshError, match=r"fakts\[mesh\]") as raised:
        await NativeNode.start(
            MeshOptions(), tmp_path / "n", "app", "https://mesh.example", "key"
        )
    assert raised.value.code is None


@pytest.mark.asyncio
async def test_no_key_and_no_node_skips_the_mesh(
    fake_arkitekt_mesh: Any, tmp_path: Path
) -> None:
    fakts = Fakts(
        grant=CountingGrant(fakts=mesh_fakts()),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=tmp_path),
    )
    async with fakts:
        assert await fakts._amesh_proxy(mesh_fakts()) is None
    assert FakeNode.started == []


@pytest.mark.asyncio
async def test_turn_needs_the_mesh_on() -> None:
    fakts = Fakts(grant=CountingGrant(fakts=mesh_fakts()), manifest=make_manifest())
    async with fakts:
        with pytest.raises(MeshError, match="not running"):
            await fakts.amesh_turn()


# --- a real node, against a lab mesh (opt-in) --------------------------------

LAB = ("ARKITEKT_TEST_MESH_URL", "ARKITEKT_TEST_MESH_KEY", "ARKITEKT_TEST_MESH_PEER")


@pytest.mark.mesh
@pytest.mark.asyncio
async def test_a_real_node(tmp_path: Path) -> None:
    """Join the lab mesh and reach its peer through the node's proxy.

    Same environment as arkirust's ``crates/mesh-py/tests/test_lab.py``:
    the control url, an auth key, and a peer serving HTTP on port 80.
    """
    pytest.importorskip("arkitekt_mesh")
    if not all(os.environ.get(name) for name in LAB):
        pytest.skip(f"set {', '.join(LAB)} to run against a lab mesh")
    import aiohttp

    node = await NativeNode.start(
        MeshOptions(timeout=60),
        tmp_path / "node",
        "fakts-test",
        coord_url=os.environ["ARKITEKT_TEST_MESH_URL"],
        auth_key=os.environ["ARKITEKT_TEST_MESH_KEY"],
    )
    try:
        assert NativeNode.has_state(tmp_path / "node")
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f"http://{os.environ['ARKITEKT_TEST_MESH_PEER']}/", proxy=node.proxy_url
            ) as response,
        ):
            assert response.status < 500
    finally:
        node.close()
