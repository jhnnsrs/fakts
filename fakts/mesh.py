"""The mesh node: the deployment's private tailnet, joined in this process.

The node is arkirust's Rust mesh client, loaded through its Python bindings
(``pip install "fakts[mesh]"``, which brings ``arkitekt-mesh``) -- the same
node the Rust fakts client runs with its native backend. No root, no TUN
device and nothing shared with a system tailscale: the node keeps its own
state directory, keyed by the app's identity (``sub``/``organization``/``hub``),
so it joins once with the key from the first token and is re-used on every
later start. It exposes a local HTTP proxy that mesh aliases are reached
through, and a TURN relay and TCP forwards for WebRTC media (LiveKit).
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from arkitekt_spec.declare.wiring import MeshError as AliasMeshError
from arkitekt_spec.declare.wiring import TurnInfo
from pydantic import BaseModel, ConfigDict, Field

from fakts.errors import FaktsError
from fakts.models import ActiveFakts, Manifest

logger = logging.getLogger(__name__)


class MeshError(FaktsError, AliasMeshError):
    """The mesh node could not be started, or did not connect.

    ``code`` is the node's own error code, as the Rust client reports it: ``needs_login``, ``locked``, ``login``,
    ``timeout``, ``locked_out``, ``start``, or ``None`` when fakts itself
    refused (the bindings are missing, the mesh is not running, ...).
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


NEEDS_LOGIN = (
    "This node is not on the mesh and no mesh key was granted; authorize "
    "the app again (without the cache) and allow mesh access"
)

NOT_INSTALLED = (
    'The mesh needs the arkitekt-mesh bindings; install them with `pip install "fakts[mesh]"`'
)

NO_KEY = (
    "This app holds no mesh key and no joined node: the server granted none (mesh "
    "access was opted out of, or the organization has no mesh). To join, allow mesh "
    "access and authorize the app again without the cache"
)


def bindings_installed() -> bool:
    """Whether the mesh bindings can be imported, without importing them."""
    try:
        return importlib.util.find_spec("arkitekt_mesh") is not None
    except ValueError:
        # Already imported, without a spec (a stand-in module).
        return sys.modules.get("arkitekt_mesh") is not None


class MeshOptions(BaseModel):
    """Run a mesh node in this process (``pip install "fakts[mesh]"``): where it
    keeps its state, and how long it may take to join.

    The node is only started when a service cannot be reached without it:
    every non-mesh alias of that service failed its challenge.
    """

    kind: Literal["node"] = "node"
    auto: bool = False
    """Use the mesh only if it is available, and say nothing when it is not.
    Without the bindings installed this is off; the login asks for a mesh key,
    and when the server grants none (the user opted out, or the organization
    has no mesh) mesh aliases are skipped quietly. Without ``auto``, both of
    those are reported (as warnings, and on the aliases that needed the mesh)."""
    force: bool = False
    """Reach every service over the mesh, and over nothing else: aliases that
    are not on the mesh are not even challenged, and a service that lists no
    mesh alias (or whose mesh alias does not answer) is unreachable. For
    proving that a deployment works over its mesh, and for networks where
    the direct addresses answer but must not be used."""

    model_config = ConfigDict(frozen=True)

    def requests_key(self) -> bool:
        """Whether a login should ask the server for a key to join with."""
        return self.force or not self.auto or bindings_installed()

    state_root: Path | None = None
    """Where node state lives (default: ``<state dir>/arkitekt/mesh``)."""
    hostname: str | None = None
    """The node's hostname (default: ``<app identifier>-<device id>``)."""
    timeout: float = 90
    """How long joining and connecting may take, in seconds."""
    tcp_buffer: int | None = None
    """Bytes of buffer per connection, each way (default: the node's own,
    1 MiB). It is the most a connection has in flight, so its throughput is at
    most this per round trip: raise it for bulk transfers over slow, far
    links, at that much memory per busy connection."""

    def resolved_state_root(self) -> Path:
        return self.state_root or _state_dir() / "arkitekt" / "mesh"

    def node_dir(self, name: str) -> Path:
        """The state directory of the node called ``name``.

        Suffixed ``-native`` as the Rust client's native backend names it, so
        a Python and a Rust app with the same identity use the same node (the
        node's own lock keeps two processes from running it at once).
        """
        return self.resolved_state_root() / f"{name}-native"


class MeshProxy(BaseModel):
    """Reach mesh-only aliases through an HTTP proxy that is already running
    (e.g. ``arkitekt mesh proxy``); this process starts no node."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["proxy"] = "proxy"
    url: str
    """The proxy, e.g. ``http://localhost:1055``."""
    force: bool = False
    """Reach every service over the mesh, and over nothing else: aliases that
    are not on the mesh are not even challenged, and a service that lists no
    mesh alias (or whose mesh alias does not answer) is unreachable. For
    proving that a deployment works over its mesh, and for networks where
    the direct addresses answer but must not be used."""


AUTO_MESH = MeshOptions(auto=True)
"""The builders' default: the mesh when it is available, silence when not."""

MeshConfig = Annotated[MeshOptions | MeshProxy, Field(discriminator="kind")]
"""How a Fakts reaches mesh aliases: its own node, or a running proxy."""


def _state_dir() -> Path:
    """The per-user state directory (as the Rust client's ``dirs`` crate
    picks it, so both keep their nodes side by side)."""
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    if sys.platform == "darwin":
        return home / "Library" / "Application Support"
    return Path(os.environ.get("XDG_STATE_HOME") or home / ".local" / "state")


def hostname_label(raw: str) -> str:
    """A DNS label: lowercase alphanumerics and dashes, at most 63 characters."""
    label = re.sub(r"[^a-z0-9]", "-", raw.lower())[:63].strip("-")
    return label or "arkitekt-app"


def _bindings() -> Any:
    try:
        import arkitekt_mesh  # type: ignore[import-not-found]
    except ImportError:
        raise MeshError(NOT_INSTALLED) from None
    return arkitekt_mesh


def _translate(error: Exception, bindings: Any, statedir: Path) -> MeshError:
    """The bindings' exception as a :class:`MeshError` with the node's code."""
    if isinstance(error, bindings.NeedsLogin):
        return MeshError(NEEDS_LOGIN, "needs_login")
    if isinstance(error, bindings.Locked):
        return MeshError(f"Another mesh node is already running in {statedir}", "locked")
    if isinstance(error, bindings.Refused):
        return MeshError(f"The mesh refused this node: {error}", "login")
    if isinstance(error, bindings.Timeout):
        return MeshError(f"The mesh did not connect in time: {error}", "timeout")
    if isinstance(error, bindings.LockedOut):
        # The message names the `nodekey:` an admin has to sign; the node stays
        # up and is let in once it is signed (tailnet lock, RFC-5).
        return MeshError(str(error), "locked_out")
    return MeshError(str(error), "start")


class NativeNode:
    """The mesh node running in this process; stop it with :meth:`close`."""

    def __init__(self, node: Any, statedir: Path) -> None:
        self._node = node
        self.proxy_url: str = node.proxy_url
        """The local HTTP proxy into the mesh, e.g. ``http://127.0.0.1:41234``."""
        self.statedir = statedir

    def __deepcopy__(self, memo: dict) -> Self:
        # A running node is shared, never copied: a deep copy of an alias
        # reached through it is still reached through it.
        return self

    @staticmethod
    def has_state(statedir: Path) -> bool:
        """Whether a node already joined in ``statedir`` (and can start without a key)."""
        return bool(_bindings().Node.has_state(str(statedir)))

    @classmethod
    async def start(
        cls,
        options: MeshOptions,
        statedir: Path,
        hostname: str,
        coord_url: str | None,
        auth_key: str | None,
    ) -> NativeNode:
        """Start the node, joining with ``auth_key`` or re-using the state in ``statedir``."""
        bindings = _bindings()
        if auth_key:
            logger.info("Joining the mesh as %s", hostname)
        # Only when set: older bindings do not take it.
        tuning = {} if options.tcp_buffer is None else {"tcp_buffer": options.tcp_buffer}
        try:
            node = await bindings.Node.start(
                str(statedir),
                hostname,
                control_url=coord_url,
                auth_key=auth_key,
                timeout=options.timeout,
                **tuning,
            )
        except bindings.MeshError as e:
            raise _translate(e, bindings, statedir) from e
        logger.info("Connected to the mesh as %s; proxy at %s", hostname, node.proxy_url)
        return cls(node, statedir)

    async def turn(self) -> TurnInfo:
        """The node's TURN relay (started on first use, then the same one)."""
        bindings = _bindings()
        try:
            info = await self._node.turn()
        except bindings.MeshError as e:
            raise MeshError(str(e)) from e
        return TurnInfo(urls=list(info.urls), username=info.username, credential=info.credential)

    async def forward(self, host: str, port: int) -> str:
        """A local ``127.0.0.1:P`` forwarding TCP to ``host:port`` on the mesh."""
        bindings = _bindings()
        try:
            return await self._node.forward(host, port)
        except bindings.MeshError as e:
            raise MeshError(str(e)) from e

    def close(self) -> None:
        self._node.close()


SETTLE = 10.0
"""Seconds a node that has just started may need until its peers answer."""

Route = tuple[str | None, "NativeNode | None", "MeshError | None"]
"""The proxy, the node that runs it, and why there is neither."""


class MeshRoute:
    """How this process reaches mesh aliases, for one entered Fakts.

    Either a running HTTP proxy (``proxy``, nothing to start) or a node this
    process starts the first time a service needs it (``options``) and closes
    on exit. Why there is no route (the node failed, no key, no bindings) is
    remembered in ``error``, so lookups do not retry a join that can take
    ``MeshOptions.timeout`` each.
    """

    def __init__(self, mesh: MeshOptions | MeshProxy | None, manifest: Manifest) -> None:
        self.options = mesh if isinstance(mesh, MeshOptions) else None
        self.proxy = mesh.url if isinstance(mesh, MeshProxy) else None
        self.forced = mesh is not None and mesh.force
        """Only mesh aliases are used (``force`` on the mesh configuration)."""
        self.manifest = manifest
        self.node: NativeNode | None = None
        self.error: MeshError | None = None
        self.started_at: float | None = None
        """When the node came up (``loop.time()``): its first connections may
        still be waiting for the peers to learn of it."""
        self._start: asyncio.Task[Route] | None = None
        self._closed = False

    @property
    def enabled(self) -> bool:
        return self.proxy is not None or self.options is not None

    def settling(self, now: float) -> bool:
        """Whether the node came up less than :data:`SETTLE` seconds before
        ``now`` (``loop.time()``): its peers may not know of it yet."""
        return self.started_at is not None and now - self.started_at < SETTLE

    def ready(self) -> tuple[str, NativeNode | None] | None:
        """The route if it costs nothing to use: a proxy, or a node already up."""
        if self.proxy:
            return self.proxy, None
        if self.node is not None:
            return self.node.proxy_url, self.node
        return None

    async def aroute(self, fakts: ActiveFakts) -> Route:
        """The HTTP proxy mesh aliases are reached through, the node that runs
        it, and why there is none: all ``None`` if the mesh is off, no node for
        a MeshProxy. Starts the node on the first call; single-flight.

        A node that cannot start is not fatal: aliases that do not need the
        mesh still resolve, and the failure is remembered (and reported on the
        mesh aliases) instead of being retried on every lookup.

        The start belongs to the route, not to the caller: cancelling this
        call leaves it running. A node whose start was abandoned half way
        would keep its state directory locked, and every later start in this
        process would find it taken.
        """
        if (route := self.ready()) is not None:
            return route[0], route[1], None
        if self.options is None:
            return None, None, None
        if self._start is None:
            self._start = asyncio.ensure_future(self._astart(fakts))
        return await asyncio.shield(self._start)

    async def _astart(self, fakts: ActiveFakts) -> Route:
        assert self.options is not None
        try:
            node = await self._anode(fakts)
        except MeshError as e:
            quiet = self.options.auto and e.code in (None, "needs_login")
            logger.log(
                logging.DEBUG if quiet else logging.WARNING,
                "The mesh node could not start: %s",
                e,
            )
            self.error = e
            return None, None, e
        except Exception as e:
            # Remembered like any other: this start is the only one there
            # will be, and every later lookup gets its outcome.
            logger.warning("The mesh node could not start", exc_info=True)
            self.error = MeshError(f"The mesh node could not start: {type(e).__name__}: {e}")
            return None, None, self.error
        if self._closed:
            # The block was left while the node was still starting.
            node.close()
            self.error = MeshError("The mesh node was closed while it was starting")
            return None, None, self.error
        self.node = node
        self.started_at = asyncio.get_running_loop().time()
        return node.proxy_url, node, None

    async def _anode(self, fakts: ActiveFakts) -> NativeNode:
        """Start the mesh node; it lives until the context exits. Its state
        directory is keyed by the app's identity, so it is joined once (with
        the key from the first token) and re-used after.
        """
        assert self.options is not None
        if self.options.auto and not bindings_installed():
            raise MeshError(NOT_INSTALLED)

        me = fakts.self
        if me.sub and me.organization and me.hub:
            identity = f"{me.sub}-{me.organization}-{me.hub}"
        else:
            identity = sha256(f"{me.deployment_name}:{self.manifest.hash()}".encode()).hexdigest()[
                :16
            ]
        statedir = self.options.node_dir(
            f"{hostname_label(self.manifest.identifier)}-{hostname_label(identity)}"
        )

        claim = fakts.mesh
        if claim is None and not NativeNode.has_state(statedir):
            raise MeshError(NO_KEY, "needs_login")
        # The grant already filled a missing coord url from the well-known;
        # a joined node remembers its coordination server.
        coord_url = claim.ionscale_coord_url if claim else None
        if claim is not None and not coord_url:
            raise MeshError("The server sent a mesh key but no coordination url")

        device = "".join(c for c in (self.manifest.device_id or "") if c.isascii() and c.isalnum())[
            :8
        ]
        hostname = self.options.hostname or hostname_label(f"{self.manifest.identifier}-{device}")
        return await NativeNode.start(
            self.options,
            statedir,
            hostname,
            coord_url=coord_url,
            auth_key=claim.ionscale_auth_key if claim else None,
        )

    def close(self) -> None:
        """Stop the node, if one was started (or as soon as it has)."""
        self._closed = True
        if self.node is not None:
            node, self.node = self.node, None
            node.close()
