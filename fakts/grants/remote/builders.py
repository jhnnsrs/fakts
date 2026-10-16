import ssl
from hashlib import sha256

import certifi
from pydantic import SecretStr

from fakts.cache.file import FileCache
from fakts.cache.nocache import NoCache
from fakts.fakts import Fakts
from fakts.grants.remote import RemoteGrant
from fakts.grants.remote.authorizers.device_code import (
    ClientKind,
    ClientRole,
    DeviceCodeAuthorizer,
)
from fakts.grants.remote.authorizers.mandate_key import HeadlessClientKind, MandateKeyAuthorizer
from fakts.grants.remote.discovery.well_known import WellKnownDiscovery
from fakts.mesh import AUTO_MESH, MeshOptions, MeshProxy
from fakts.models import Manifest
from fakts.protocols import FaktsCache


def _resolve_ssl(ssl_context: ssl.SSLContext | None) -> ssl.SSLContext:
    """One TLS context for the whole client.

    Discovery, the grant and the runtime each used to build their own, so
    pinning a private CA on ``Fakts`` silently left discovery and the device
    flow on the default bundle.
    """
    return ssl_context or ssl.create_default_context(cafile=certifi.where())


def _build_cache(url: str, manifest: Manifest, cache_file: str, no_cache: bool) -> FaktsCache:
    """Build the default cache: a FileCache bound to the server url and the
    manifest hash, so a changed manifest *or* a different server invalidates
    previously cached fakts (instead of silently serving the old server's
    configuration)."""
    if no_cache:
        return NoCache()
    # The "v2:" prefix makes a protocol-v1 cache miss deterministically
    # rather than relying on its now-invalid shape failing validation.
    bound_hash = sha256(f"v2:{url}:{manifest.hash()}".encode()).hexdigest()
    return FileCache(cache_file=cache_file, hash=bound_hash)


def _build_remote_fakts(
    url: str,
    manifest: Manifest,
    authorizer: DeviceCodeAuthorizer | MandateKeyAuthorizer,
    *,
    context: ssl.SSLContext,
    cache_file: str,
    no_cache: bool,
    allow_insecure_transport: bool,
    mesh: MeshOptions | MeshProxy | None,
) -> Fakts:
    """What every remote builder assembles: discovery against ``url`` with
    the one TLS context, the given authorizer, and the url+manifest-bound
    cache."""
    return Fakts(
        grant=RemoteGrant(
            discovery=WellKnownDiscovery(
                url=url, auto_protocols=["https", "http"], ssl_context=context
            ),
            authorizer=authorizer,
        ),
        cache=_build_cache(url, manifest, cache_file, no_cache),
        manifest=manifest,
        allow_insecure_transport=allow_insecure_transport,
        ssl_context=context,
        mesh=mesh,
    )


def build_device_code_fakts(
    url: str,
    manifest: Manifest,
    *,
    cache_file: str = ".fakts_cache.json",
    no_cache: bool = False,
    headless: bool = False,
    requested_client_kind: ClientKind = ClientKind.DEVELOPMENT,
    requested_client_role: ClientRole = ClientRole.INTERFACE,
    timeout: int | None = None,
    allow_insecure_transport: bool = False,
    ssl_context: ssl.SSLContext | None = None,
    mesh: MeshOptions | MeshProxy | None = AUTO_MESH,
) -> Fakts:
    """Build a ready-to-use Fakts for the device code flow.

    This is the standard way to connect an app to a Fakts server for the
    first time: the server is discovered through its well-known endpoint,
    the user approves the app once in the browser (device code flow), and
    the resulting configuration is cached in ``cache_file`` so subsequent
    runs start without any interaction.

    Example:
        ```python
        fakts = build_device_code_fakts(
            url="http://localhost:8000",
            manifest=Manifest(
                identifier="my-app",
                version="0.1.0",
                scopes=["openid"],
                requirements=[Requirement(key="rekuest", service="live.arkitekt.rekuest")],
            ),
        )

        async with fakts:
            alias = await fakts.aget_alias("rekuest")
        ```

    Parameters
    ----------
    url : str
        The url of the Fakts server (its well-known endpoint is derived
        from this).
    manifest : Manifest
        The manifest of this app. Used both to register the app on the
        server and to declare its service requirements.
    cache_file : str, optional
        Where to cache the granted configuration, by default
        ".fakts_cache.json". Relative paths are resolved against the
        current working directory — use an absolute, per-app path if your
        app is started from varying directories.
    no_cache : bool, optional
        Disable caching entirely (every run re-runs the device code
        flow), by default False.
    headless : bool, optional
        Do not try to open a browser; only print the configuration URL
        and code, by default False.
    requested_client_kind : ClientKind, optional
        The kind of client to register on the server, by default
        ClientKind.DEVELOPMENT.
    timeout : Optional[int], optional
        How long (seconds) to wait for the user to approve the device
        code. Defaults to the code's expiration time.
    ssl_context : Optional[ssl.SSLContext], optional
        TLS context used for *every* call — discovery, the device flow, the
        token endpoint, alias challenges and the report. Pass one to trust a
        private CA; without it, certifi's bundle applies throughout.
    mesh : MeshOptions | MeshProxy | None, optional
        Reach mesh-only aliases. The default, ``MeshOptions(auto=True)``, uses
        the mesh when it is available: with the bindings installed (``pip
        install "fakts[mesh]"``) the login asks for a mesh key, and the node
        starts only when a service is reachable no other way. The server may
        grant no key (the user opted out, or the organization has no mesh);
        mesh aliases are then skipped quietly. ``MeshOptions()`` does the same
        but reports what is missing; ``MeshProxy(url=...)`` uses a proxy that
        is already running (e.g. ``arkitekt mesh proxy``); ``None`` is off.

    Returns
    -------
    Fakts
        A fully wired Fakts instance (use it as a context manager).
    """
    context = _resolve_ssl(ssl_context)
    return _build_remote_fakts(
        url,
        manifest,
        DeviceCodeAuthorizer(
            manifest=manifest,
            open_browser=not headless,
            requested_client_kind=requested_client_kind,
            requested_client_role=requested_client_role,
            timeout=timeout,
            allow_insecure_transport=allow_insecure_transport,
            ssl_context=context,
            # Only a node of our own needs a key; a proxy is already on the mesh.
            request_auth_key=isinstance(mesh, MeshOptions) and mesh.requests_key(),
        ),
        context=context,
        cache_file=cache_file,
        no_cache=no_cache,
        allow_insecure_transport=allow_insecure_transport,
        mesh=mesh,
    )


def build_mandate_key_fakts(
    url: str,
    manifest: Manifest,
    key: str,
    *,
    cache_file: str = ".fakts_cache.json",
    no_cache: bool = False,
    allow_insecure_transport: bool = False,
    ssl_context: ssl.SSLContext | None = None,
    requested_client_kind: HeadlessClientKind = HeadlessClientKind.DEVELOPMENT,
    requested_client_role: ClientRole = ClientRole.INTERFACE,
    request_auth_key: bool = False,
    mesh: MeshOptions | MeshProxy | None = AUTO_MESH,
) -> Fakts:
    """Build a ready-to-use Fakts that logs in with a mandate key (headless).

    A mandate key is a standing credential someone with the right to grant it
    handed out in advance (kontrol, a hub, a deployer, the deployment config);
    it logs this app in as them without any user interaction. There is no
    refresh token: the client logs in again whenever its access token runs out,
    so a revoked key stops working within one access-token lifetime.

    Parameters
    ----------
    url : str
        The url of the Fakts server.
    manifest : Manifest
        The manifest of this app. It must be covered by the mandate's pin.
    key : str
        The mandate key (``FAKTS_MANDATE_KEY``).
    cache_file : str, optional
        Where to cache the granted configuration, by default
        ".fakts_cache.json".
    no_cache : bool, optional
        Disable caching entirely, by default False.
    requested_client_kind, requested_client_role : optional
        What the client is (development, desktop or mobile) and does.
    request_auth_key : bool, optional
        Ask for a mesh key on the first login; the mandate must allow it.
    mesh : MeshOptions | MeshProxy | None, optional
        Reach mesh-only aliases (default ``MeshOptions(auto=True)``, see
        :func:`build_device_code_fakts`).

    Returns
    -------
    Fakts
        A fully wired Fakts instance (use it as a context manager).
    """
    context = _resolve_ssl(ssl_context)
    return _build_remote_fakts(
        url,
        manifest,
        MandateKeyAuthorizer(
            manifest=manifest,
            key=SecretStr(key),
            requested_client_kind=requested_client_kind,
            requested_client_role=requested_client_role,
            request_auth_key=request_auth_key,
            allow_insecure_transport=allow_insecure_transport,
            ssl_context=context,
        ),
        context=context,
        cache_file=cache_file,
        no_cache=no_cache,
        allow_insecure_transport=allow_insecure_transport,
        mesh=mesh,
    )
