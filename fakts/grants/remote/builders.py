import ssl
from hashlib import sha256
from typing import Optional

import certifi

from fakts.cache.file import FileCache
from fakts.cache.nocache import NoCache
from fakts.fakts import Fakts
from fakts.grants.hard import HardFaktsGrant
from fakts.grants.remote import RemoteGrant
from fakts.grants.remote.authorizers.device_code import (
    ClientKind,
    ClientRole,
    DeviceCodeAuthorizer,
)
from fakts.grants.remote.authorizers.redeem import RedeemAuthorizer
from fakts.grants.remote.discovery.well_known import WellKnownDiscovery
from fakts.models import ActiveFakts, Manifest
from fakts.protocols import FaktsCache


def _resolve_ssl(ssl_context: Optional[ssl.SSLContext]) -> ssl.SSLContext:
    """One TLS context for the whole client.

    Discovery, the grant and the runtime each used to build their own, so
    pinning a private CA on ``Fakts`` silently left discovery and the device
    flow on the default bundle.
    """
    return ssl_context or ssl.create_default_context(cafile=certifi.where())


def _build_cache(
    url: str, manifest: Manifest, cache_file: str, no_cache: bool
) -> FaktsCache:
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


def build_device_code_fakts(
    url: str,
    manifest: Manifest,
    *,
    cache_file: str = ".fakts_cache.json",
    no_cache: bool = False,
    headless: bool = False,
    requested_client_kind: ClientKind = ClientKind.DEVELOPMENT,
    requested_client_role: ClientRole = ClientRole.INTERFACE,
    timeout: Optional[int] = None,
    allow_insecure_transport: bool = False,
    ssl_context: Optional[ssl.SSLContext] = None,
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

    Returns
    -------
    Fakts
        A fully wired Fakts instance (use it as a context manager).
    """
    context = _resolve_ssl(ssl_context)
    return Fakts(
        grant=RemoteGrant(
            discovery=WellKnownDiscovery(
                url=url, auto_protocols=["https", "http"], ssl_context=context
            ),
            authorizer=DeviceCodeAuthorizer(
                manifest=manifest,
                open_browser=not headless,
                requested_client_kind=requested_client_kind,
                requested_client_role=requested_client_role,
                timeout=timeout,
                allow_insecure_transport=allow_insecure_transport,
                ssl_context=context,
            ),
        ),
        cache=_build_cache(url, manifest, cache_file, no_cache),
        manifest=manifest,
        allow_insecure_transport=allow_insecure_transport,
        ssl_context=context,
    )


def build_redeem_fakts(
    url: str,
    manifest: Manifest,
    token: str,
    *,
    cache_file: str = ".fakts_cache.json",
    no_cache: bool = False,
    allow_insecure_transport: bool = False,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Fakts:
    """Build a ready-to-use Fakts for the redeem flow (headless/CI).

    A redeem token is issued by the Fakts server beforehand and lets this
    app register itself without any user interaction — useful in CI
    pipelines, scripts and other headless environments.

    Parameters
    ----------
    url : str
        The url of the Fakts server.
    manifest : Manifest
        The manifest of this app.
    token : str
        The redeem token issued by the server (single-use).
    cache_file : str, optional
        Where to cache the granted configuration, by default
        ".fakts_cache.json". Relative paths are resolved against the
        current working directory — use an absolute, per-app path if your
        app is started from varying directories.
    no_cache : bool, optional
        Disable caching entirely, by default False.

    Returns
    -------
    Fakts
        A fully wired Fakts instance (use it as a context manager).
    """
    context = _resolve_ssl(ssl_context)
    return Fakts(
        grant=RemoteGrant(
            discovery=WellKnownDiscovery(
                url=url, auto_protocols=["https", "http"], ssl_context=context
            ),
            authorizer=RedeemAuthorizer(
                manifest=manifest,
                token=token,
                allow_insecure_transport=allow_insecure_transport,
                ssl_context=context,
            ),
        ),
        cache=_build_cache(url, manifest, cache_file, no_cache),
        manifest=manifest,
        allow_insecure_transport=allow_insecure_transport,
        ssl_context=context,
    )


def build_remote_testing(value: ActiveFakts) -> "HardFaktsGrant":
    """Builds a grant for testing purposes.

    Always yields the same configuration, without touching the network. No
    longer a `RemoteGrant`: under protocol v2 even a static session has to
    come from somewhere, and pretending otherwise meant faking a token
    endpoint. `HardFaktsGrant` says the same thing honestly.
    """
    return HardFaktsGrant(fakts=value)


def build_redeem_grant(
    url: str,
    manifest: Manifest,
    redeem_token: str,
    *,
    allow_insecure_transport: bool = False,
) -> RemoteGrant:
    """Builds a remote grant that redeems a token (grant only, no Fakts).

    Prefer :func:`build_redeem_fakts` unless you need to wire the Fakts
    instance yourself.

    Discovery is well-known rather than static: under protocol v2 the token
    endpoint is published by the server, and a static endpoint would have to
    guess it.
    """
    return RemoteGrant(
        discovery=WellKnownDiscovery(url=url, auto_protocols=["https", "http"]),
        authorizer=RedeemAuthorizer(
            manifest=manifest,
            token=redeem_token,
            allow_insecure_transport=allow_insecure_transport,
        ),
    )
