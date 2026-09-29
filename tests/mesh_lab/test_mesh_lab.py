"""fakts against a real mesh: a real control server (ionskale), the real node
(arkitekt-mesh), and a peer only reachable over the mesh.

What the fake node in ``tests/test_mesh.py`` cannot show: that fakts joins
with the granted key, challenges a mesh alias through the node's proxy, hands
back an alias that carries the node, and that the forward and relay that
alias offers lead somewhere.
"""

from pathlib import Path

import aiohttp
import pytest

from fakts import Fakts
from fakts.mesh import MeshOptions, NativeNode
from fakts.models import ActiveFakts, Alias, Instance, MeshClaim

from ..helpers import CountingGrant, make_fakts_value, make_manifest
from .conftest import MeshLab

pytestmark = [pytest.mark.integration, pytest.mark.mesh]


@pytest.fixture(autouse=True)
def trust_the_lab_ca(mesh_lab: MeshLab, monkeypatch: pytest.MonkeyPatch) -> None:
    """The node checks the control server's (and DERP's) certificate."""
    monkeypatch.setenv("ARKITEKT_MESH_CA_FILE", mesh_lab.ca_file)


def peer_fakts(lab: MeshLab, *, with_key: bool = True) -> ActiveFakts:
    """One service, only reachable over the mesh: the peer."""
    value = make_fakts_value()
    value.auth.report_endpoint = None
    value.instances["test"] = Instance(
        service="test_service",
        identifier="test_instance",
        aliases=[Alias(id="peer", host=lab.peer, port=80, challenge="ht", kind="mesh")],
    )
    if with_key:
        value.mesh = MeshClaim(ionscale_auth_key=lab.app_key, ionscale_coord_url=lab.coord_url)
    return value


def lab_fakts(value: ActiveFakts, state_root: Path) -> Fakts:
    return Fakts(
        grant=CountingGrant(fakts=value),
        manifest=make_manifest(),
        mesh=MeshOptions(state_root=state_root, timeout=60),
        # The first packets may wait for a DERP connection.
        alias_challenge_timeout=30,
    )


@pytest.mark.asyncio
async def test_a_mesh_alias_is_resolved_and_reached_through_its_node(
    mesh_lab: MeshLab, tmp_path: Path
) -> None:
    async with lab_fakts(peer_fakts(mesh_lab), tmp_path) as fakts:
        # The node joined with the granted key, and the challenge went through it.
        alias = await fakts.aget_alias("test")
        assert alias.id == "peer"
        assert alias.proxy is not None

        async with aiohttp.ClientSession() as session:
            # Over the node's HTTP proxy, as every GraphQL link goes.
            async with session.get(alias.to_http_path(), proxy=alias.proxy) as response:
                assert response.status == 200

            # Over a local TCP forward the alias hands out, as LiveKit's
            # signaling goes.
            local = await alias.aforward()
            assert local.startswith("127.0.0.1:")
            async with session.get(f"http://{local}/") as response:
                assert response.status == 200

        # The relay a WebRTC client is pointed at: the node's own, on loopback.
        # That it relays is arkirust's to show (crates/mesh-py/tests/test_lab.py).
        turn = await alias.aturn()
        assert turn.urls and all("127.0.0.1" in url for url in turn.urls)
        assert turn.username and turn.credential


@pytest.mark.asyncio
async def test_a_joined_node_rejoins_without_a_key(mesh_lab: MeshLab, tmp_path: Path) -> None:
    async with lab_fakts(peer_fakts(mesh_lab), tmp_path) as fakts:
        await fakts.aget_alias("test")
    assert any(NativeNode.has_state(d) for d in tmp_path.iterdir())

    # No key this time: the node's saved state is enough.
    async with lab_fakts(peer_fakts(mesh_lab, with_key=False), tmp_path) as fakts:
        alias = await fakts.aget_alias("test")
        local = await alias.aforward()
        async with (
            aiohttp.ClientSession() as session,
            session.get(f"http://{local}/") as response,
        ):
            assert response.status == 200


@pytest.mark.asyncio
async def test_a_real_node(mesh_lab: MeshLab, tmp_path: Path) -> None:
    """The node on its own: join, and reach the peer through its proxy."""
    node = await NativeNode.start(
        MeshOptions(timeout=60),
        tmp_path / "node",
        "fakts-test",
        coord_url=mesh_lab.coord_url,
        auth_key=mesh_lab.app_key,
    )
    try:
        assert NativeNode.has_state(tmp_path / "node")
        async with (
            aiohttp.ClientSession() as session,
            session.get(f"http://{mesh_lab.peer}/", proxy=node.proxy_url) as response,
        ):
            assert response.status == 200
    finally:
        node.close()


@pytest.mark.asyncio
async def test_a_host_that_is_not_on_the_mesh_is_not_resolved(
    mesh_lab: MeshLab, tmp_path: Path
) -> None:
    """The other tests pass only because the peer is on the mesh."""
    from fakts.errors import CompositionError

    value = peer_fakts(mesh_lab)
    value.instances["test"].aliases = [
        Alias(id="nobody", host="not-on-the-mesh", port=80, challenge="ht", kind="mesh")
    ]
    fakts = lab_fakts(value, tmp_path)
    fakts.alias_challenge_timeout = 5
    async with fakts:
        with pytest.raises(CompositionError, match="nobody"):
            await fakts.aget_alias("test")
