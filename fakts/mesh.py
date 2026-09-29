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

import logging
import os
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any, Self

from arkitekt_spec.declare.wiring import MeshError as AliasMeshError
from arkitekt_spec.declare.wiring import TurnInfo
from pydantic import BaseModel

from fakts.errors import FaktsError
from fakts.models import ActiveFakts, Manifest

logger = logging.getLogger(__name__)


class MeshError(FaktsError, AliasMeshError):
    """The mesh node could not be started, or did not connect.

    ``code`` is the node's own error code, as the Rust client and
    ``arkitekt-meshd`` report it: ``needs_login``, ``locked``, ``login``,
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


class MeshOptions(BaseModel):
    """Where the mesh node keeps its state, and how long it may take to join."""

    state_root: Path | None = None
    """Where node state lives (default: ``<state dir>/arkitekt/mesh``)."""
    hostname: str | None = None
    """The node's hostname (default: ``<app identifier>-<device id>``)."""
    timeout: float = 90
    """How long joining and connecting may take, in seconds."""

    def resolved_state_root(self) -> Path:
        return self.state_root or _state_dir() / "arkitekt" / "mesh"

    def node_dir(self, name: str) -> Path:
        """The state directory of the node called ``name``.

        Suffixed ``-native`` as the Rust client's native backend names it, so
        a Python and a Rust app with the same identity use the same node (the
        node's own lock keeps two processes from running it at once).
        """
        return self.resolved_state_root() / f"{name}-native"


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
        try:
            node = await bindings.Node.start(
                str(statedir),
                hostname,
                control_url=coord_url,
                auth_key=auth_key,
                timeout=options.timeout,
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


class MeshRoute:
    """How this process reaches mesh aliases, for one entered Fakts.

    Either a running HTTP proxy (``proxy``, nothing to start) or a node this
    process starts on first use (``options``) and closes on exit. A node that
    cannot start is remembered (``error``), so lookups do not retry a join
    that can take ``MeshOptions.timeout`` each.
    """

    def __init__(self, options: MeshOptions | None, proxy: str | None, manifest: Manifest) -> None:
        self.options = options
        self.proxy = proxy
        self.manifest = manifest
        self.node: NativeNode | None = None
        self.error: MeshError | None = None

    async def aroute(
        self, fakts: ActiveFakts
    ) -> tuple[str | None, NativeNode | None, MeshError | None]:
        """The HTTP proxy mesh aliases are reached through, the node that runs
        it, and why there is none: all ``None`` if the mesh is off, no node for
        an external ``mesh_proxy``.

        A node that fails to start is not fatal: aliases that do not need the
        mesh still resolve, and the failure is remembered (and reported on the
        mesh aliases) instead of being retried on every lookup.
        """
        if self.proxy:
            return self.proxy, None, None
        if not any(
            alias.is_mesh() for instance in fakts.instances.values() for alias in instance.aliases
        ):
            return None, None, None
        if self.error is not None:
            return None, None, self.error
        try:
            node = await self._anode(fakts)
        except MeshError as e:
            logger.warning("The mesh node could not start: %s", e)
            self.error = e
            return None, None, e
        return (node.proxy_url, node, None) if node else (None, None, None)

    async def _anode(self, fakts: ActiveFakts) -> NativeNode | None:
        """The mesh node, started on first use; it lives until the context
        exits. Its state directory is keyed by the app's identity, so it is
        joined once (with the key from the first token) and re-used after.
        """
        if self.options is None:
            return None
        if self.node is not None:
            return self.node

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
            logger.warning(
                "The mesh is enabled, but this app holds no mesh key; mesh aliases "
                "will be skipped (authorize again without the cache and allow mesh "
                "access to join)."
            )
            return None
        # The grant already filled a missing coord url from the well-known;
        # a joined node remembers its coordination server.
        coord_url = claim.ionscale_coord_url if claim else None
        if claim is not None and not coord_url:
            raise MeshError("The server sent a mesh key but no coordination url")

        device = "".join(c for c in (self.manifest.device_id or "") if c.isascii() and c.isalnum())[
            :8
        ]
        hostname = self.options.hostname or hostname_label(f"{self.manifest.identifier}-{device}")
        self.node = await NativeNode.start(
            self.options,
            statedir,
            hostname,
            coord_url=coord_url,
            auth_key=claim.ionscale_auth_key if claim else None,
        )
        return self.node

    def close(self) -> None:
        """Stop the node, if one was started."""
        if self.node is not None:
            node, self.node = self.node, None
            node.close()
