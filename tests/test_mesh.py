"""The mesh: aliases only reachable over the deployment's tailnet, reached
through the in-process mesh node's HTTP proxy (or a running one).

``arkitekt_mesh`` is faked here; the real bindings are tested against a
tailnet in arkirust's ``crates/mesh-py``, and by ``test_a_real_node`` below
when a lab mesh is configured.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest
import pytest_asyncio
from aiohttp import web
from arkitekt_spec.declare.wiring import MeshError as AliasMeshError

from fakts import Fakts
from fakts.errors import AttemptOutcome, CompositionError
from fakts.grants.remote.authorizers.device_code import DeviceCodeAuthorizer
from fakts.grants.remote.models import FaktsEndpoint
from fakts.mesh import MeshError, MeshOptions, MeshProxy, NativeNode, hostname_label
from fakts.models import ActiveFakts, Alias, Instance, Manifest, MeshClaim, Requirement, SelfFakt
from fakts.oauth2 import TokenResponse, merge_token_response

from .helpers import CountingGrant, make_fakts_value, make_manifest


def test_hostnames_are_dns_labels() -> None:
    assert hostname_label("My App_v2") == "my-app-v2"
    assert hostname_label("--x--") == "x"
    assert hostname_label("!!!") == "arkitekt-app"
    assert len(hostname_label("a" * 80)) == 63


def test_nodes_live_in_the_native_directory(tmp_path: Path) -> None:
    # The Rust client's native backend names its node directories the same way.
    assert MeshOptions(state_root=tmp_path).node_dir("app-x") == tmp_path / "app-x-native"


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
    sent: list[dict] = []

    async def capture(url: str, payload: dict, **kwargs: Any) -> dict:
        sent.append(payload)
        return {}

    monkeypatch.setattr("fakts.grants.remote.authorizers.device_code.oauth2.apost_json", capture)
    endpoint = FaktsEndpoint(device_authorization_endpoint="http://localhost/device")
    await DeviceCodeAuthorizer(manifest=make_manifest()).arequest_code(endpoint)
    await DeviceCodeAuthorizer(manifest=make_manifest(), request_auth_key=True).arequest_code(
        endpoint
    )
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
    assert ActiveFakts.model_validate_json(refreshed.model_dump_json()).mesh == first.mesh


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
    seen: list[str] = []

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
        mesh=MeshProxy(url=proxy),
    )
    async with fakts:
        alias = await fakts.aget_alias("test")
        assert alias.id == "mesh"
        assert alias.proxy == proxy
        assert seen == ["GET http://100.64.0.9:8080/test/ht"]
        # Served from the alias map, still carrying the proxy.
        again = await fakts.aget_alias("test")
        assert again.proxy == proxy
        # An external proxy is no node of this process: nothing to forward through.
        with pytest.raises(AliasMeshError, match="ARKITEKT_MESH_PROXY"):
            await again.aturn()
        # The instance (what gets cached) never holds it.
        assert fakts.loaded_fakts is not None
        assert all(a.proxy is None for a in fakts.loaded_fakts.instances["test"].aliases)


@pytest.mark.asyncio
async def test_a_proxy_that_cannot_reach_the_service_is_not_the_service_answering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mesh proxy answers a peer it cannot reach with a 502 and the reason.
    That is no answer of the service's, and the reason is what helps."""

    async def handle(request: web.Request) -> web.Response:
        return web.Response(status=502, text="100.64.0.9:8080: no peer has this address")

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    value = mesh_fakts()
    value.instances["test"].aliases.pop()
    fakts = Fakts(
        grant=CountingGrant(fakts=value),
        manifest=make_manifest(),
        mesh=MeshProxy(url=f"http://127.0.0.1:{port}"),
    )
    try:
        async with fakts:
            with pytest.raises(CompositionError) as raised:
                await fakts.aget_alias("test", omit_report=True)
    finally:
        await runner.cleanup()
    (attempt,) = raised.value.failures[0].attempts
    assert attempt.outcome is AttemptOutcome.UNREACHABLE
    assert "no peer has this address" in str(raised.value)


@pytest.mark.asyncio
async def test_mesh_aliases_are_skipped_without_the_mesh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    challenged: list[str] = []

    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None) -> bool:
        challenged.append(alias.id)
        return True

    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge)
    fakts = Fakts(grant=CountingGrant(fakts=mesh_fakts()), manifest=make_manifest())
    async with fakts:
        alias = await fakts.aget_alias("test")
    assert alias.id == "direct"
    assert alias.proxy is None
    assert challenged == ["direct"]


# --- the native backend (arkitekt_mesh, faked here; the real one is tested
# against a tailnet in arkirust's crates/mesh-py) ---------------------------


class FakeNode:
    started: ClassVar[list[dict]] = []

    def __init__(self, statedir: str, proxy_url: str):
        self.statedir = statedir
        self.proxy_url = proxy_url
        self.closed = False
        self.forwards: list[tuple] = []

    @staticmethod
    async def start(statedir, hostname, control_url=None, auth_key=None, timeout=90, **tuning):
        FakeNode.started.append(
            {
                "statedir": statedir,
                "hostname": hostname,
                "control_url": control_url,
                "auth_key": auth_key,
                "tuning": tuning,
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
        # Nothing an older arkitekt-mesh would not take.
        assert start["tuning"] == {}

        # The alias carries the node it is reached through.
        turn = await alias.aturn()
        assert turn.urls == ["turn:127.0.0.1:3478?transport=udp"]
        assert turn.username == "u" and turn.credential == "c"
        assert await alias.aforward() == "127.0.0.1:5555"
        assert await alias.aforward(7880) == "127.0.0.1:5555"
        # Also when served again from the alias map.
        again = await fakts.aget_alias("test")
        assert fakts._mesh_route is not None
        assert again._mesh is fakts._mesh_route.node
        node = fakts._mesh_route.node
        assert node is not None and node._node.forwards == [
            ("100.64.0.9", 8080),
            ("100.64.0.9", 7880),
        ]
    assert node._node.closed


@pytest.mark.asyncio
async def test_the_tcp_buffer_reaches_the_node(fake_arkitekt_mesh: Any, tmp_path: Path) -> None:
    options = MeshOptions(tcp_buffer=4 << 20)
    await NativeNode.start(options, tmp_path / "n", "app", "https://mesh.example", "tskey")
    assert FakeNode.started[0]["tuning"] == {"tcp_buffer": 4 << 20}


@pytest.mark.asyncio
async def test_native_needs_login_is_a_mesh_error(fake_arkitekt_mesh: Any, tmp_path: Path) -> None:
    with pytest.raises(MeshError, match="no mesh key was granted") as raised:
        await NativeNode.start(MeshOptions(), tmp_path / "n", "app", "https://mesh.example", None)
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
        await NativeNode.start(MeshOptions(), tmp_path / "n", "app", "https://mesh.example", "key")
    assert raised.value.code == code


@pytest.mark.asyncio
async def test_missing_bindings_say_what_to_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "arkitekt_mesh", None)
    with pytest.raises(MeshError, match=r"fakts\[mesh\]") as raised:
        await NativeNode.start(MeshOptions(), tmp_path / "n", "app", "https://mesh.example", "key")
    assert raised.value.code is None


@pytest.mark.asyncio
async def test_no_key_and_no_node_skips_the_mesh(fake_arkitekt_mesh: Any, tmp_path: Path) -> None:
    fakts = Fakts(
        grant=CountingGrant(fakts=mesh_fakts()),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=tmp_path),
    )
    async with fakts:
        assert fakts._mesh_route is not None
        proxy, node, error = await fakts._mesh_route.aroute(mesh_fakts())
        assert (proxy, node) == (None, None)
        assert error is not None and error.code == "needs_login"
        assert "opted out" in str(error)
    assert FakeNode.started == []


def test_a_mesh_error_is_the_spec_s_too() -> None:
    """Whoever holds only an Alias catches the spec's MeshError; a node's
    failure is fakts' MeshError, and must be caught by the same clause."""
    assert issubclass(MeshError, AliasMeshError)


def test_a_node_is_shared_by_deep_copies() -> None:
    from copy import deepcopy

    from fakts.mesh import NativeNode

    node = NativeNode.__new__(NativeNode)
    alias = Alias(id="a", host="db", kind="mesh").through_mesh("http://127.0.0.1:1", node)
    assert "_mesh" not in alias.model_dump_json()
    assert deepcopy(alias)._mesh is node


def keyed(value: ActiveFakts) -> ActiveFakts:
    value.mesh = MeshClaim(ionscale_auth_key="k", ionscale_coord_url="https://mesh.example")
    return value


def challenge_only(*reachable: str) -> Any:
    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None, **kw: Any) -> bool:
        return alias.id in reachable

    return challenge


@pytest.mark.asyncio
async def test_no_node_is_started_for_what_is_reachable_without_it(
    fake_arkitekt_mesh: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mesh alias comes first, but the direct one answers: a node would
    only cost a join (up to MeshOptions.timeout) for nothing."""
    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge_only("mesh", "direct"))
    fakts = Fakts(
        grant=CountingGrant(fakts=keyed(mesh_fakts())),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=tmp_path),
    )
    async with fakts:
        alias = await fakts.aget_alias("test", omit_report=True)
    assert alias.id == "direct"
    assert FakeNode.started == []


@pytest.mark.asyncio
async def test_a_service_last_reached_over_the_mesh_does_not_wait_for_the_others(
    fake_arkitekt_mesh: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mesh alias is first because it won last time, and the direct one
    does not answer: the node starts after the head start, not after the
    direct alias has timed out."""

    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None, **kw: Any) -> bool:
        if alias.id == "direct":
            await asyncio.Event().wait()
        return True

    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge)
    FakeNode.proxy = "http://127.0.0.1:1"  # type: ignore[attr-defined]
    fakts = Fakts(
        grant=CountingGrant(fakts=keyed(mesh_fakts())),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=tmp_path),
        alias_head_start=0.01,
        alias_challenge_timeout=30,
    )
    async with fakts:
        alias = await asyncio.wait_for(fakts.aget_alias("test", omit_report=True), 5)
    assert alias.id == "mesh" and alias.proxy == FakeNode.proxy  # type: ignore[attr-defined]
    assert len(FakeNode.started) == 1


@pytest.mark.asyncio
async def test_a_forced_mesh_is_the_only_way_taken(
    fake_arkitekt_mesh: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The direct alias answers, and would win: forced, it is not even asked,
    and the node starts without waiting for it."""
    asked: list[str] = []

    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None, **kw: Any) -> bool:
        asked.append(alias.id)
        return True

    value = keyed(mesh_fakts())
    value.instances["test"].aliases.reverse()  # the direct one first
    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge)
    FakeNode.proxy = "http://127.0.0.1:1"  # type: ignore[attr-defined]
    fakts = Fakts(
        grant=CountingGrant(fakts=value),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=tmp_path, force=True),
        alias_head_start=30,
    )
    async with fakts:
        alias = await asyncio.wait_for(fakts.aget_alias("test", omit_report=True), 5)
        unchallenged = await fakts.aget_alias("test", omit_challenge=True, force_refresh=True)
    assert alias.id == unchallenged.id == "mesh" and alias.proxy
    assert asked == ["mesh"]
    assert len(FakeNode.started) == 1


@pytest.mark.asyncio
async def test_a_forced_mesh_does_not_fall_back(mesh_proxy: Any) -> None:
    """Forced means forced: a mesh alias that does not answer is a failure,
    whatever else would, and so is a service that lists none."""
    proxy, _ = mesh_proxy

    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None, **kw: Any) -> bool:
        return alias.id == "direct"

    value = mesh_fakts()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Fakts, "_achallenge_alias", challenge)
        fakts = Fakts(
            grant=CountingGrant(fakts=value),
            manifest=make_manifest(),
            mesh=MeshProxy(url=proxy, force=True),
        )
        async with fakts:
            with pytest.raises(CompositionError) as raised:
                await fakts.aget_alias("test", omit_report=True)
        (failure,) = raised.value.failures
        assert [(a.alias_id, a.outcome) for a in failure.attempts] == [
            ("mesh", AttemptOutcome.REFUSED),
            ("direct", AttemptOutcome.SKIPPED),
        ]
        assert "the mesh is forced" in str(raised.value)

        value.instances["test"].aliases.pop(0)  # no mesh alias left
        fakts = Fakts(
            grant=CountingGrant(fakts=value),
            manifest=make_manifest(),
            mesh=MeshProxy(url=proxy, force=True),
        )
        async with fakts:
            with pytest.raises(CompositionError, match="lists no alias on the mesh"):
                await fakts.aget_alias("test", omit_report=True)


@pytest.mark.asyncio
async def test_a_node_that_just_joined_is_asked_again(
    fake_arkitekt_mesh: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first connection through a new node waits for the peer to hear of
    it, which can outlast one challenge: silence is not yet a no."""
    asked = 0

    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None, **kw: Any) -> bool:
        nonlocal asked
        asked += 1
        if asked == 1:
            await asyncio.Event().wait()
        return True

    value = keyed(mesh_fakts())
    value.instances["test"].aliases.pop()
    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge)
    FakeNode.proxy = "http://127.0.0.1:1"  # type: ignore[attr-defined]
    fakts = Fakts(
        grant=CountingGrant(fakts=value),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=tmp_path),
        alias_challenge_timeout=0.05,
    )
    async with fakts:
        assert (await fakts.aget_alias("test", omit_report=True)).id == "mesh"
    assert asked == 2


@pytest.mark.asyncio
async def test_a_node_start_is_not_abandoned_when_a_direct_alias_wins(
    fake_arkitekt_mesh: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The direct alias answers while the node is still joining. Cancelling
    the join would leave a node nobody holds, with its state directory
    locked: it is let finish, kept, and closed with the block."""
    asked = asyncio.Event()
    answer = asyncio.Event()
    joined = asyncio.Event()
    nodes: list[FakeNode] = []

    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None, **kw: Any) -> bool:
        asked.set()
        await answer.wait()
        return True

    async def slow_start(statedir: str, hostname: str, **kw: Any) -> FakeNode:
        FakeNode.started.append({"statedir": statedir})
        await joined.wait()
        nodes.append(FakeNode(statedir, "http://127.0.0.1:1"))
        return nodes[0]

    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge)
    monkeypatch.setattr(FakeNode, "start", staticmethod(slow_start))
    fakts = Fakts(
        grant=CountingGrant(fakts=keyed(mesh_fakts())),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=tmp_path),
        alias_head_start=0.01,
        alias_challenge_timeout=30,
    )
    async with fakts:
        lookup = asyncio.ensure_future(fakts.aget_alias("test", omit_report=True))
        await asked.wait()
        while not FakeNode.started:
            await asyncio.sleep(0.005)
        answer.set()
        assert (await asyncio.wait_for(lookup, 5)).id == "direct"

        route = fakts._mesh_route
        assert route is not None and route.node is None, "the join is still under way"
        joined.set()
        while route.node is None:
            await asyncio.sleep(0)
        assert route.node._node is nodes[0]
    assert nodes[0].closed
    assert len(FakeNode.started) == 1


@pytest.mark.asyncio
async def test_a_node_that_comes_up_after_the_block_is_closed(
    fake_arkitekt_mesh: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    joined = asyncio.Event()
    nodes: list[FakeNode] = []

    async def slow_start(statedir: str, hostname: str, **kw: Any) -> FakeNode:
        await joined.wait()
        nodes.append(FakeNode(statedir, "http://127.0.0.1:1"))
        return nodes[0]

    async def challenge(self: Fakts, alias: Alias, challenge_key: Any = None, **kw: Any) -> bool:
        if alias.id == "direct":
            await asyncio.sleep(0.05)
        return True

    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge)
    monkeypatch.setattr(FakeNode, "start", staticmethod(slow_start))
    fakts = Fakts(
        grant=CountingGrant(fakts=keyed(mesh_fakts())),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=tmp_path),
        alias_head_start=0.01,
    )
    async with fakts:
        assert (await fakts.aget_alias("test", omit_report=True)).id == "direct"
        route = fakts._mesh_route
    joined.set()
    assert route is not None and route._start is not None
    await route._start
    assert nodes[0].closed and route.node is None


@pytest.mark.asyncio
async def test_a_running_node_keeps_the_alias_order(
    fake_arkitekt_mesh: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once another service started the node, a mesh alias listed first is
    used first again -- deferring is about not *starting* a node."""
    value = keyed(mesh_fakts())
    value.instances["only_mesh"] = Instance(
        service="mesh_service",
        identifier="mesh_instance",
        aliases=[Alias(id="only", host="100.64.0.10", challenge="ht", kind="mesh")],
    )
    manifest = Manifest(
        version="0.1.0",
        identifier="test_manifest",
        scopes=["openid"],
        requirements=[
            Requirement(key="only_mesh", service="mesh_service"),
            Requirement(key="test", service="test_service", optional=True),
        ],
    )
    # Down at first, so that no alias of it is remembered as the one to ask first.
    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge_only("only"))
    fakts = Fakts(
        grant=CountingGrant(fakts=value),
        manifest=manifest,
        mesh=MeshOptions(state_root=tmp_path),
    )
    async with fakts:
        await fakts.aget_alias("only_mesh", omit_report=True)
        assert len(FakeNode.started) == 1
        monkeypatch.setattr(Fakts, "_achallenge_alias", challenge_only("only", "mesh", "direct"))
        alias = await fakts.aget_alias("test", omit_report=True, force_refresh=True)
    assert alias.id == "mesh"
    assert len(FakeNode.started) == 1


@pytest.mark.asyncio
async def test_services_that_need_the_node_at_once_start_it_once(
    fake_arkitekt_mesh: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = keyed(make_fakts_value())
    value.auth.report_endpoint = None
    keys = ["a", "b", "c"]
    value.instances = {
        key: Instance(
            service=f"{key}_service",
            identifier=f"{key}_instance",
            aliases=[Alias(id=key, host=f"100.64.0.{i}", challenge="ht", kind="mesh")],
        )
        for i, key in enumerate(keys)
    }
    manifest = Manifest(
        version="0.1.0",
        identifier="test_manifest",
        scopes=["openid"],
        requirements=[Requirement(key=key, service=f"{key}_service") for key in keys],
    )
    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge_only(*keys))
    fakts = Fakts(
        grant=CountingGrant(fakts=value), manifest=manifest, mesh=MeshOptions(state_root=tmp_path)
    )
    async with fakts:
        for key in keys:
            assert (await fakts.aget_alias(key, omit_report=True)).proxy is not None
    assert len(FakeNode.started) == 1


@pytest.mark.asyncio
async def test_a_node_that_cannot_start_does_not_block_plain_aliases(
    fake_arkitekt_mesh: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One MeshError used to abort resolution of every alias, and every later
    lookup retried the join (up to MeshOptions.timeout each)."""

    async def cannot_start(statedir, hostname, control_url=None, auth_key=None, timeout=90):
        FakeNode.started.append({"statedir": statedir})
        raise FakeTimeout("the coordination server did not answer")

    value = keyed(mesh_fakts())
    value.instances["plain"] = Instance(
        service="plain_service",
        identifier="plain_instance",
        aliases=[Alias(id="plain", host="localhost", challenge="ht")],
    )
    manifest = Manifest(
        version="0.1.0",
        identifier="test_manifest",
        scopes=["openid"],
        requirements=[
            Requirement(key="plain", service="plain_service"),
            # Its direct alias is down: only the mesh would reach it.
            Requirement(key="test", service="test_service", optional=True),
        ],
    )
    monkeypatch.setattr(FakeNode, "start", staticmethod(cannot_start))
    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge_only("plain", "mesh"))
    fakts = Fakts(
        grant=CountingGrant(fakts=value), manifest=manifest, mesh=MeshOptions(state_root=tmp_path)
    )

    async with fakts:
        assert (await fakts.aget_alias("plain", omit_report=True)).id == "plain"
        assert await fakts.aget_alias_or_none("test", omit_report=True) is None
        await fakts.aget_alias("plain", omit_report=True, force_refresh=True)
        assert "not available: The mesh did not connect in time" in (
            fakts.report_map["test"].reason or ""
        )
    assert len(FakeNode.started) == 1, "the failed join was retried"


@pytest.mark.asyncio
async def test_auto_without_the_bindings_is_quietly_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, "arkitekt_mesh", None)
    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge_only("mesh"))
    assert not MeshOptions(auto=True).requests_key(), "no key for a node that cannot run"
    assert MeshOptions().requests_key()

    fakts = Fakts(
        grant=CountingGrant(fakts=keyed(mesh_fakts())),
        manifest=make_manifest(),
        mesh=MeshOptions(auto=True),
    )
    with caplog.at_level("WARNING", logger="fakts.mesh"):
        async with fakts:
            with pytest.raises(CompositionError, match=r"fakts\[mesh\]"):
                await fakts.aget_alias("test", omit_report=True)
    assert not [r for r in caplog.records if r.name == "fakts.mesh"]


@pytest.mark.asyncio
async def test_auto_without_a_key_is_quiet(
    fake_arkitekt_mesh: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The user opted out of the mesh, or the organization has none: no key
    came, and that is an answer, not a problem to warn about."""
    monkeypatch.setattr(Fakts, "_achallenge_alias", challenge_only("direct"))
    for options, warned in (
        (MeshOptions(auto=True, state_root=tmp_path), False),
        (MeshOptions(state_root=tmp_path), True),
    ):
        caplog.clear()
        fakts = Fakts(
            grant=CountingGrant(fakts=mesh_fakts()), manifest=make_manifest(), mesh=options
        )
        with caplog.at_level("WARNING", logger="fakts.mesh"):
            async with fakts:
                # The direct alias answers, so nothing needs the mesh yet...
                assert (await fakts.aget_alias("test", omit_report=True)).id == "direct"
                assert fakts._mesh_route is not None
                # ...and when something does, it is simply not there.
                _, _, error = await fakts._mesh_route.aroute(mesh_fakts())
                assert error is not None and error.code == "needs_login"
        assert bool([r for r in caplog.records if r.name == "fakts.mesh"]) is warned
    assert FakeNode.started == []


def test_the_builders_use_the_mesh_when_it_is_available(
    fake_arkitekt_mesh: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakts import build_device_code_fakts, build_redeem_fakts

    fakts = build_device_code_fakts("http://localhost:8000", make_manifest(), no_cache=True)
    assert fakts.mesh == MeshOptions(auto=True)
    assert isinstance(fakts.grant.authorizer, DeviceCodeAuthorizer)  # type: ignore[attr-defined]
    assert fakts.grant.authorizer.request_auth_key  # type: ignore[attr-defined]
    assert build_redeem_fakts("http://localhost:8000", make_manifest(), "t").mesh == MeshOptions(
        auto=True
    )

    monkeypatch.setitem(sys.modules, "arkitekt_mesh", None)
    fakts = build_device_code_fakts("http://localhost:8000", make_manifest(), no_cache=True)
    assert not fakts.grant.authorizer.request_auth_key  # type: ignore[attr-defined]

    fakts = build_device_code_fakts(
        "http://localhost:8000", make_manifest(), no_cache=True, mesh=None
    )
    assert fakts.mesh is None
    assert not fakts.grant.authorizer.request_auth_key  # type: ignore[attr-defined]


def test_the_mesh_config_is_one_tagged_union() -> None:
    """One `mesh` field replaced `mesh` + `mesh_proxy` (and its precedence rule);
    the tag decides, so a plain config cannot validate as the wrong kind."""
    from fakts.grants.remote.builders import build_device_code_fakts

    grant = CountingGrant(fakts=mesh_fakts())
    by_dict = Fakts(
        grant=grant, manifest=make_manifest(), mesh={"kind": "proxy", "url": "http://p:1055"}
    )
    assert isinstance(by_dict.mesh, MeshProxy) and by_dict.mesh.url == "http://p:1055"
    assert isinstance(
        Fakts(grant=grant, manifest=make_manifest(), mesh={"kind": "node"}).mesh, MeshOptions
    )

    def asks_for_a_key(mesh: Any) -> bool:
        fakts = build_device_code_fakts(
            "https://x.example", make_manifest(), mesh=mesh, no_cache=True
        )
        return fakts.grant.authorizer.request_auth_key  # type: ignore[attr-defined]

    assert asks_for_a_key(MeshOptions()) is True
    assert asks_for_a_key(MeshProxy(url="http://p:1055")) is False
    assert asks_for_a_key(None) is False
