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
from pathlib import Path
from typing import Any, Optional, Self

from arkitekt_spec.declare.wiring import MeshError as AliasMeshError
from arkitekt_spec.declare.wiring import TurnInfo
from pydantic import BaseModel

from fakts.errors import FaktsError

logger = logging.getLogger(__name__)


class MeshError(FaktsError, AliasMeshError):
    """The mesh node could not be started, or did not connect.

    ``code`` is the node's own error code, as the Rust client and
    ``arkitekt-meshd`` report it: ``needs_login``, ``locked``, ``login``,
    ``timeout``, ``locked_out``, ``start``, or ``None`` when fakts itself
    refused (the bindings are missing, the mesh is not running, ...).
    """

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


NEEDS_LOGIN = (
    "This node is not on the mesh and no mesh key was granted; authorize "
    "the app again (without the cache) and allow mesh access"
)

NOT_INSTALLED = (
    "The mesh needs the arkitekt-mesh bindings; install them with "
    '`pip install "fakts[mesh]"`'
)


class MeshOptions(BaseModel):
    """Where the mesh node keeps its state, and how long it may take to join."""

    state_root: Optional[Path] = None
    """Where node state lives (default: ``<state dir>/arkitekt/mesh``)."""
    hostname: Optional[str] = None
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
        return MeshError(
            f"Another mesh node is already running in {statedir}", "locked"
        )
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
        coord_url: Optional[str],
        auth_key: Optional[str],
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
        logger.info(
            "Connected to the mesh as %s; proxy at %s", hostname, node.proxy_url
        )
        return cls(node, statedir)

    async def turn(self) -> TurnInfo:
        """The node's TURN relay (started on first use, then the same one)."""
        bindings = _bindings()
        try:
            info = await self._node.turn()
        except bindings.MeshError as e:
            raise MeshError(str(e)) from e
        return TurnInfo(
            urls=list(info.urls), username=info.username, credential=info.credential
        )

    async def forward(self, host: str, port: int) -> str:
        """A local ``127.0.0.1:P`` forwarding TCP to ``host:port`` on the mesh."""
        bindings = _bindings()
        try:
            return await self._node.forward(host, port)
        except bindings.MeshError as e:
            raise MeshError(str(e)) from e

    def close(self) -> None:
        self._node.close()
