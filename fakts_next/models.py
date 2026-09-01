from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Any, List, Optional
import json
from enum import Enum
from hashlib import sha256


class GrantStatus(str, Enum):
    """The grant status of a single service requirement.

    Reported by the server per requirement key, so the client can tell a
    deliberate denial apart from a service the deployment simply does not
    offer. Servers that do not support statuses omit them entirely, in
    which case the status is UNKNOWN (unless an instance was granted,
    which is unambiguous).
    """

    GRANTED = "granted"
    """The user granted access and an instance was composed."""
    DENIED = "denied"
    """The user explicitly declined access to this service."""
    UNAVAILABLE = "unavailable"
    """The deployment does not offer this service."""
    UNKNOWN = "unknown"
    """The server did not report a (known) status for this requirement."""


class Alias(BaseModel):
    """An alias is a way of contacting a service instance in Fakts.

    It contains the host, port, ssl flag, path and challenge.
    """

    id: str
    """The unique identifier of the alias."""
    host: str
    port: Optional[int] = None
    """The port is optional, if not set, the default port for the service will be"""
    ssl: bool = False
    """The ssl flag indicates if the service should be accessed via SSL or not. If set to True, the service will be accessed via HTTPS, otherwise it will be accessed via HTTP."""
    path: Optional[str] = None
    """The path is optional, if not set, the default path for the service will be used."""
    challenge: str = Field(
        default="",
        description="""The challenge is a string that is used to verify the alias. It should be """,
    )
    public: bool = False
    """Whether this alias is reachable from outside the deployment's own
    network. Informational: the server decides which aliases to hand out,
    the client just tries them in order."""

    @property
    def challenge_path(self) -> str:
        """The challenge_path of the alias. Its a reachable http path that can be used to verify if the alias is accessible by the client."""
        return self.to_http_path(self.challenge)

    def to_http_path(self, append: Optional[str] = None) -> str:
        """Convert the alias to a HTTP path

        This method converts the alias to a HTTP path, which can be used to access the service.
        If the port is not set, the default port for the service will be used.
        If the ssl flag is set, the service will be accessed via HTTPS, otherwise it will be accessed via HTTP.

        Args:
            append (Optional[str], optional): An optional string to append to the path. Defaults to None.

        Returns:
            str: The HTTP path for the service
        """
        protocol = "https" if self.ssl else "http"

        url = f"{protocol}://{self.host}"
        if self.port:
            url += f":{self.port}"
        if self.path:
            url += f"/{self.path.lstrip('/')}"
        if append:
            url += f"/{append.lstrip('/')}"

        return url

    def to_ws_path(self, append: Optional[str] = None) -> str:
        """Convert the alias to a WebSocket path

        This method converts the alias to a WebSocket path, which can be used to access the service.
        If the port is not set, the default port for the service will be used.
        If the ssl flag is set, the service will be accessed via wss, otherwise it will be accessed via ws.

        Args:
            append (Optional[str], optional): An optional string to append to the path. Defaults to None.

        Returns:
            str: The WebSocket path for the service
        """
        protocol = "wss" if self.ssl else "ws"

        url = f"{protocol}://{self.host}"
        if self.port:
            url += f":{self.port}"
        if self.path:
            url += f"/{self.path.lstrip('/')}"
        if append:
            url += f"/{append.lstrip('/')}"

        return url


class ChallengeKey(BaseModel):
    """A public key a service uses to prove its identity in alias challenges.

    Registering a key is entirely optional per service instance: without
    one, the plain 200-challenge applies. When an instance carries a
    challenge key, the client sends a random nonce with each alias
    challenge and the service must answer with a signature over the
    (domain-separated) nonce, made with the matching private key. The
    client then verifies the signature against this key — a plain 200 is
    no longer enough.
    """

    kind: str = "ed25519"
    """The signature scheme. Currently only "ed25519" is supported; a key
    of an unsupported kind is ignored (with a warning), so newer schemes
    do not break older clients."""
    key: str
    """The base64-encoded raw public key (32 bytes for ed25519)."""


class Instance(BaseModel):
    """Configuration for a service in Fakts."""

    service: str
    identifier: str
    aliases: list[Alias] = []
    challenge_key: Optional[ChallengeKey] = None
    """Optional public key of the service. If set, alias challenges must
    answer with a valid signature (see ChallengeKey); the same key is used
    for all aliases of the instance (one service identity, many routes)."""


class AuthFakt(BaseModel):
    """The OAuth2 credentials this client holds for a deployment.

    Protocol v2 is refresh-token based: the interactive flows (device code,
    redeem) end at the token endpoint, which hands back an access token *and*
    a rotating refresh token. There is no ``client_secret`` — fakts clients
    are public OAuth2 clients (the server sets
    ``token_endpoint_auth_method="none"``), so the refresh chain *is* the
    credential.

    Both ``client_id`` and ``refresh_token`` are required on every renewal:
    the token endpoint authenticates the client before it looks at the
    refresh token, and then checks the token actually belongs to it.
    """

    client_id: str
    """Server-minted client identifier. It comes from the device
    authorization response and is echoed by every token response — it is
    never derived from the manifest. Re-approval rotates it, so always
    persist whatever the latest response carried."""
    token_endpoint: str
    """Absolute URL of the OAuth2 token endpoint, taken from discovery."""
    report_endpoint: Optional[str] = None
    """Where to report the alias resolution outcome. Derived from the
    endpoint's ``base_url`` (the server does not publish it). Endpoints that
    do not support reporting simply omit it, and the client skips the report."""
    scopes: List[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    """The *granted* scopes, as returned by the token endpoint. Under
    per-requirement consent this legitimately differs from what was asked
    for, so it must never be validated against the request."""

    refresh_token: str
    """The live rotating secret. Every use invalidates the previous value, so
    a rotated token must be persisted before the new access token is used."""
    access_token: Optional[str] = None
    """The current access token. Persisted so that sibling processes sharing
    a cache can reuse it instead of each racing to refresh; may be stale on
    load, which is what ``expires_at`` is for."""
    expires_at: Optional[float] = None
    """Absolute unix timestamp at which ``access_token`` expires. ``None``
    means the server declared no lifetime: treat the token as opaque and
    refresh only when it is actually rejected."""
    refresh_issued_at: Optional[float] = None
    """When the current refresh token was issued (unix ts). Lets the client
    recognise a blown sliding window locally instead of guessing at an
    ``invalid_grant``."""
    chain_started_at: Optional[float] = None
    """When this refresh chain began (unix ts), carried across rotations.
    Servers cap the absolute lifetime of a chain independently of the
    sliding window, so this is what detects "this authorization is simply
    too old"."""
    token_type: str = "Bearer"


class SelfFakt(BaseModel):
    """SelfFakt is a special kind of Fakt that is used to identify the Fakts server itself"""

    deployment_name: str
    alias: Alias


class ActiveFakts(BaseModel):
    """The active Fakts are the Fakts that are currently active for this client"""

    self: SelfFakt
    """SelfFakt is a special kind of Fakt that is used to identify the Fakts server itself"""
    auth: AuthFakt
    instances: dict[str, Instance] = {}
    statuses: dict[str, GrantStatus] = {}
    """Per-requirement grant status as reported by the server (keyed like
    ``instances``). Optional: servers that do not support statuses omit it,
    and unknown status values are coerced to UNKNOWN instead of failing
    validation (so a newer server cannot break older clients)."""

    @field_validator("statuses", mode="before")
    @classmethod
    def _coerce_unknown_statuses(cls, v: Any) -> Any:
        if isinstance(v, dict):
            known = {status.value for status in GrantStatus}
            return {
                key: (
                    value
                    if isinstance(value, GrantStatus) or value in known
                    else GrantStatus.UNKNOWN
                )
                for key, value in v.items()
            }
        return v


class Requirement(BaseModel):
    """A requirement is a way to specify a requirement for a service instance in Fakts."""

    key: str
    service: str
    """ The service is the service that will be used to fill the key, it will be used to find the correct instance. It needs to fullfill
    the reverse domain naming scheme"""
    optional: bool = False
    """ The optional flag indicates if the requirement is optional or not. Users should be able to use the client even if the requirement is not met. """
    description: Optional[str] = None
    """ The description is a human readable description of the requirement. Will be show to the user when asking for the requirement."""


class PublicSource(BaseModel):
    """A public source kind is a way to specify a kind of public source."""

    kind: str
    """ The name of the public source kind, e.g. "git", "docker", etc."""
    url: str


class Manifest(BaseModel):
    """A manifest for an app that can be installed in ArkitektNext

    Manifests are used to describe apps that can be installed in ArkitektNext.
    They provide information about the app, such as the
    its globally unique identifier, the version, the scopes it needs, etc.

    This Manifest is send to the Fakts server on initial app configuration,
    and is used to register the app with the Fakts server, which in turn
    will prompt the user to grant the app access to establish itself as
    an ArkitektNext app (and therefore as an OAuth2 client) (see more in the
    Fakts documentation).

    """

    version: str
    """ The version of the app TODO: Should this be a semver? """
    identifier: str
    """ The globally unique identifier of the app: TODO: Should we check for a reverse domain name? """
    scopes: List[str]
    """ Scopes that this app should request from the user """
    logo: Optional[str] = None
    """ A URL to the logo of the app TODO: We should enforce this to be a http URL as local paths won't work """
    requirements: Optional[List[Requirement]] = Field(default_factory=lambda: [])
    """ Requirements that this app has TODO: What are the requirements? """
    node_id: Optional[str] = None
    """ The node ID of the app instance, will be set automatically to the current node ID """
    public_sources: Optional[List[PublicSource]] = Field(default_factory=lambda: [])

    description: Optional[str] = None
    """ A human readable description of the app """

    model_config = ConfigDict(extra="forbid")
    """ Configuration for the pydantic model to forbid extra fields """

    def hash(self) -> str:
        """Hash the manifest

        A manifest describes all the  metadata of an app. This method
        hashes the manifest to create a unique hash for the current configuration of the app.
        This hash can be used to check if the app has changed since the last time it was run,
        and can be used to invalidate caches.

        Returns:
            str: The hash of the manifest

        """

        unsorted_dict = self.model_dump()

        # Order must not affect the hash: the hash gates the cache, so a
        # manifest that is merely written differently would otherwise
        # invalidate it and force the user through the grant again.
        # `requirements` and `public_sources` are both Optional, so normalise
        # to a list before sorting rather than assuming one is there.
        unsorted_dict["requirements"] = sorted(
            unsorted_dict.get("requirements") or [],
            key=lambda x: (x["key"], x["service"]),
        )
        unsorted_dict["public_sources"] = sorted(
            unsorted_dict.get("public_sources") or [],
            key=lambda x: (x["kind"], x["url"]),
        )
        unsorted_dict["scopes"] = sorted(unsorted_dict.get("scopes") or [])

        # JSON encode the dictionary
        json_dd = json.dumps(unsorted_dict, sort_keys=True)
        # Hash the JSON encoded dictionary
        return sha256(json_dd.encode()).hexdigest()

    @field_validator("identifier", mode="after")
    def check_identifier(cls, v: str) -> str:
        """Check the identifier of the manifest
        This method checks the identifier of the manifest to ensure that it is a valid identifier.
        """
        if "/" in v:
            raise ValueError(f"The app identifier must not contain a '/': got '{v}'")
        if len(v) == 0:
            raise ValueError("The app identifier must not be empty")
        if len(v) >= 256:
            raise ValueError(
                f"The app identifier must be shorter than 256 characters: got {len(v)} characters"
            )
        return v
