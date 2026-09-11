import ssl
from typing import List, Optional, Protocol, runtime_checkable

import certifi
from pydantic import BaseModel, ConfigDict, Field

from fakts.oauth2 import TokenResponse


class SSLContextModel(BaseModel):
    """Base model that carries an SSL context and allows arbitrary types.

    Shared by the remote grant components (discovery, authorizers) that need
    to make TLS connections to a fakts server.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    """An ssl context to use for the connection to the endpoint."""


class FaktsEndpoint(BaseModel):
    """A discovered fakts server, as described by its well-known document.

    Under protocol v2 this doubles as OAuth 2.0 authorization-server
    metadata: the server publishes ``token_endpoint`` and
    ``device_authorization_endpoint`` alongside the fakts-specific members,
    unprefixed, in the same flat document.

    Every endpoint URL is absolute — the server builds them with
    ``build_absolute_uri`` and deployments commonly sit under a script-name
    prefix such as ``/lok``. Never reconstruct one by concatenating onto
    ``issuer``.

    ``extra="allow"`` is deliberate: the document also carries ``mesh_*``
    and ``hub_*`` members that this client does not model but other tools
    read off the same fetch.
    """

    model_config = ConfigDict(extra="allow")

    base_url: str = "http://localhost:8000/f/"
    """The base URL of the fakts app. The report endpoint is derived from
    it, because the server does not publish one."""
    name: str = "Helper"
    """A human readable name for the endpoint"""
    description: Optional[str] = None
    """A human readable description for the endpoint"""

    issuer: Optional[str] = None
    """The OAuth2 issuer identifier."""
    token_endpoint: Optional[str] = None
    """Absolute URL of the OAuth2 token endpoint. Every grant — device code,
    redeem, refresh — is a POST here."""
    device_authorization_endpoint: Optional[str] = None
    """Absolute URL of the device authorization endpoint. Non-standard in
    one respect: it takes a JSON body carrying the fakts manifest, and it
    also performs the client registration."""
    jwks_uri: Optional[str] = None
    """Where the server publishes the keys its access tokens are signed with."""
    grant_types_supported: List[str] = Field(default_factory=list)
    token_endpoint_auth_methods_supported: List[str] = Field(default_factory=list)
    configure: Optional[str] = None
    """The user-facing approval page template, containing a literal
    ``{code}`` placeholder. Informational — the device authorization
    response carries a ready-made ``verification_uri_complete``."""

    version: Optional[str] = None
    """The version of the server software (informational)"""
    protocol_version: Optional[str] = None
    """The version of the fakts protocol the server speaks. Servers that
    do not advertise it are treated as speaking protocol version "1"."""

    @property
    def report_endpoint(self) -> str:
        """Where to POST alias reports.

        Derived rather than discovered: the server routes this at
        ``{base_url}report/`` but does not advertise it in the well-known
        document.
        """
        return self.base_url.rstrip("/") + "/report/"


@runtime_checkable
class Authorizer(Protocol):
    """Turns a discovered endpoint into a live OAuth2 session.

    Replaces protocol v1's ``Demander`` + ``Claimer`` pair. There is no
    longer a two-step "obtain an artifact, then trade it for configuration":
    the token endpoint does both at once, returning the tokens *and* the
    fakts configuration in a single response.
    """

    requires_user_interaction: bool
    """Whether authorizing needs a human at a browser.

    This is what makes unattended recovery safe to automate. Re-running an
    *interactive* grant mints a new client and causes the server to delete
    the previous one — which would kill every sibling process sharing the
    cache — so it must never happen behind the user's back. Non-interactive
    grants (redeem, static) have no such hazard and may re-run freely.
    """

    async def aauthorize(self, endpoint: FaktsEndpoint) -> TokenResponse:
        """Negotiate a session with the endpoint.

        Returns the token response, including the fakts extension members
        (``self``, ``instances``, ``statuses``) the server merged into it.
        """
        ...


@runtime_checkable
class Discovery(Protocol):
    """Discovery is the abstract base class for discovery mechanisms

    A discovery mechanism is a way to find a Fakts endpoint
    that can be used to retrieve the configuration.

    This class provides an asynchronous interface, as the discovery can
    envolve lenghty operations such as network requests or waiting for
    user input.
    """

    async def adiscover(self) -> FaktsEndpoint:
        """Discovers an endpoint.

        This method should return an endpoint that can be used to retrieve
        the configuration. If no endpoint can be found, it should raise
        a DiscoveryError.

        Returns
        -------
        FaktsEndpoint
            The endpoint that can be used to retrieve the configuration.
        """
        ...
