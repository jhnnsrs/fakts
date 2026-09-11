from hashlib import sha256
from typing import Optional

from fakts_next.cache.file import FileCache
from fakts_next.cache.nocache import NoCache
from fakts_next.fakts import Fakts
from fakts_next.grants.remote import RemoteGrant
from fakts_next.grants.remote.claimers.post import ClaimEndpointClaimer
from fakts_next.grants.remote.claimers.static import StaticClaimer
from fakts_next.grants.remote.demanders.device_code import (
    ClientKind,
    DeviceCodeDemander,
)
from fakts_next.grants.remote.demanders.redeem import RedeemDemander
from fakts_next.grants.remote.demanders.static import StaticDemander
from fakts_next.grants.remote.discovery.static import StaticDiscovery
from fakts_next.grants.remote.discovery.well_known import WellKnownDiscovery
from fakts_next.grants.remote.models import ActiveFakts, FaktsEndpoint
from fakts_next.models import Manifest
from fakts_next.protocols import FaktsCache


def _build_cache(
    url: str, manifest: Manifest, cache_file: str, no_cache: bool
) -> FaktsCache:
    """Build the default cache: a FileCache bound to the server url and the
    manifest hash, so a changed manifest *or* a different server invalidates
    previously cached fakts (instead of silently serving the old server's
    configuration)."""
    if no_cache:
        return NoCache()
    bound_hash = sha256(f"{url}:{manifest.hash()}".encode()).hexdigest()
    return FileCache(cache_file=cache_file, hash=bound_hash)


def build_device_code_fakts(
    url: str,
    manifest: Manifest,
    *,
    cache_file: str = ".fakts_cache.json",
    no_cache: bool = False,
    headless: bool = False,
    requested_client_kind: ClientKind = ClientKind.DEVELOPMENT,
    timeout: Optional[int] = None,
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

    Returns
    -------
    Fakts
        A fully wired Fakts instance (use it as a context manager).
    """
    return Fakts(
        grant=RemoteGrant(
            discovery=WellKnownDiscovery(url=url, auto_protocols=["https", "http"]),
            demander=DeviceCodeDemander(
                manifest=manifest,
                open_browser=not headless,
                requested_client_kind=requested_client_kind,
                timeout=timeout,
            ),
            claimer=ClaimEndpointClaimer(),
        ),
        cache=_build_cache(url, manifest, cache_file, no_cache),
        manifest=manifest,
    )


def build_redeem_fakts(
    url: str,
    manifest: Manifest,
    token: str,
    *,
    cache_file: str = ".fakts_cache.json",
    no_cache: bool = False,
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
    return Fakts(
        grant=RemoteGrant(
            discovery=WellKnownDiscovery(url=url, auto_protocols=["https", "http"]),
            demander=RedeemDemander(manifest=manifest, token=token),
            claimer=ClaimEndpointClaimer(),
        ),
        cache=_build_cache(url, manifest, cache_file, no_cache),
        manifest=manifest,
    )


def build_remote_testing(value: ActiveFakts) -> RemoteGrant:
    """Builds a remote grant for testing purposes

    Will always return the same value when claiming.

    Parameters
    ----------
    value : ActiveFakts
        The value to return when claiming

    Returns
    -------
    RemoteGrant
        The remote grant

    """
    return RemoteGrant(
        discovery=StaticDiscovery(
            endpoint=FaktsEndpoint(base_url="https://example.com")
        ),
        claimer=StaticClaimer(value=value),
        demander=StaticDemander(token="token"),  # type: ignore
    )


def build_redeem_grant(url: str, manifest: Manifest, redeem_token: str) -> RemoteGrant:
    """Builds a remote grant that redeems a token (grant only, no Fakts).

    Prefer :func:`build_redeem_fakts` unless you need to wire the Fakts
    instance yourself.
    """
    return RemoteGrant(
        discovery=StaticDiscovery(endpoint=FaktsEndpoint(base_url=url)),
        claimer=ClaimEndpointClaimer(),
        demander=RedeemDemander(manifest=manifest, token=redeem_token),
    )


def build_remote_testing_with_token(fakts_next_url: str, token: str) -> RemoteGrant:
    """Builds a remote grant for testing purposes

    This grant will use the given token to demand the configuration from fakts_next.
    This is great for testing purposes, or when an api token is known at compile time.

    Parameters
    ----------
    fakts_next_url : str
        The url of the fakts server
    token : str
        The static token to use for claiming

    Returns
    -------
    RemoteGrant
        The remote grant

    """
    return RemoteGrant(
        discovery=StaticDiscovery(endpoint=FaktsEndpoint(base_url=fakts_next_url)),
        claimer=ClaimEndpointClaimer(),
        demander=StaticDemander(token=token),  # type: ignore
    )
