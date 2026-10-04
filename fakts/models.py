import json
from enum import Enum
from hashlib import sha256
from typing import Any

from arkitekt_spec import AppManifest, Requirement
from arkitekt_spec.declare.wiring import Alias
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


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
    challenge_key: ChallengeKey | None = None
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
    report_endpoint: str | None = None
    """Where to report the alias resolution outcome. Derived from the
    endpoint's ``base_url`` (the server does not publish it). Endpoints that
    do not support reporting simply omit it, and the client skips the report."""
    revocation_endpoint: str | None = None
    """Where a logout revokes the session (RFC 7009), when the server
    advertises one. Without it a logout only forgets the session here."""
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    """The *granted* scopes, as returned by the token endpoint. Under
    per-requirement consent this legitimately differs from what was asked
    for, so it must never be validated against the request."""

    refresh_token: str
    """The live rotating secret. Every use invalidates the previous value, so
    a rotated token must be persisted before the new access token is used."""
    access_token: str | None = None
    """The current access token. Persisted so that sibling processes sharing
    a cache can reuse it instead of each racing to refresh; may be stale on
    load, which is what ``expires_at`` is for."""
    expires_at: float | None = None
    """Absolute unix timestamp at which ``access_token`` expires. ``None``
    means the server declared no lifetime: treat the token as opaque and
    refresh only when it is actually rejected."""
    refresh_issued_at: float | None = None
    """When the current refresh token was issued (unix ts). Lets the client
    recognise a blown sliding window locally instead of guessing at an
    ``invalid_grant``."""
    chain_started_at: float | None = None
    """When this refresh chain began (unix ts), carried across rotations.
    Servers cap the absolute lifetime of a chain independently of the
    sliding window, so this is what detects "this authorization is simply
    too old"."""
    token_type: str = "Bearer"


class SelfFakt(BaseModel):
    """SelfFakt is a special kind of Fakt that is used to identify the Fakts server itself"""

    deployment_name: str
    alias: Alias
    sub: str | None = None
    """The user the app acts for."""
    organization: str | None = None
    """The organization the app was authorized in."""
    hub: str | None = None
    """The hub the app is bound to (its mesh tag is ``tag:hub-<hub>``)."""

    @field_validator("sub", "organization", "hub", mode="before")
    @classmethod
    def _ids_as_strings(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int) else v


class MeshClaim(BaseModel):
    """A key to join the deployment's mesh, granted once with the first
    token when the app asked for it (``request_auth_key``) and the approver
    allowed it. Kept across refreshes: the node joins with it only once."""

    ionscale_auth_key: str
    ionscale_coord_url: str | None = None


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
    mesh: MeshClaim | None = None
    """The mesh key, if one was granted (see :class:`MeshClaim`)."""

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


class PublicSource(BaseModel):
    """A public source kind is a way to specify a kind of public source."""

    kind: str
    """ The name of the public source kind, e.g. "git", "docker", etc."""
    url: str


#: The fields ``Manifest.hash`` covers: exactly the ones the login manifest had before
#: it was built on ``arkitekt_spec.AppManifest``, so no existing cache or grant moves.
LOGIN_HASH_FIELDS = (
    "version",
    "identifier",
    "scopes",
    "logo",
    "requirements",
    "device_id",
    "public_sources",
    "description",
)
#: What of each requirement / public source the login hash covers. Pinned: the
#: fields that were hashed when these became fixed (see
#: tests/test_manifest_hash_stability.py).
REQUIREMENT_HASH_FIELDS = ("key", "service", "optional", "description")
PUBLIC_SOURCE_HASH_FIELDS = ("kind", "url")


class Manifest(AppManifest):
    """The app's identity as it logs in: arkitekt-spec's ``AppManifest``, plus runtime fields.

    Sent to the fakts server on initial app configuration, which prompts the user
    to grant the app access to establish itself as an Arkitekt app (an OAuth2
    client). The identity fields are the spec's -- the same ones a deployment
    records -- and the fields below exist only at login.
    """

    requirements: list[Requirement] | None = Field(default_factory=lambda: [])
    """ The services the app needs, filled in by the server's instances. """
    device_id: str | None = Field(
        default=None, validation_alias=AliasChoices("device_id", "node_id")
    )
    """ The device this app instance runs on; the runtime sets it. ``node_id`` is the
    deprecated spelling, still read from older configs and servers. """
    public_sources: list[PublicSource] | None = Field(default_factory=lambda: [])

    model_config = ConfigDict(extra="forbid")
    """ A manifest is written in code: a misspelled field must fail, not vanish. """

    def hash(self) -> str:
        """Hash the manifest

        A manifest describes all the  metadata of an app. This method
        hashes the manifest to create a unique hash for the current configuration of the app.
        This hash can be used to check if the app has changed since the last time it was run,
        and can be used to invalidate caches.

        Returns:
            str: The hash of the manifest

        """

        # Only the fields that have always identified a login. The spec's newer
        # identity fields (``author``, ``entrypoint``) are left out on purpose:
        # adding them would change every app's hash, and with it the cache key and
        # the grant binding -- one forced device-code login for every app.
        unsorted_dict = self.model_dump(include=set(LOGIN_HASH_FIELDS))

        # Order must not affect the hash: the hash gates the cache, so a
        # manifest that is merely written differently would otherwise
        # invalidate it and force the user through the grant again.
        # `requirements` and `public_sources` are both Optional, so normalise
        # to a list before sorting rather than assuming one is there.
        # Each entry is reduced to the fields that have always been hashed, so a
        # field arkitekt-spec adds to Requirement later does not move every
        # app's hash either.
        unsorted_dict["requirements"] = sorted(
            (
                {field: entry.get(field) for field in REQUIREMENT_HASH_FIELDS}
                for entry in unsorted_dict.get("requirements") or []
            ),
            key=lambda x: (x["key"], x["service"]),
        )
        unsorted_dict["public_sources"] = sorted(
            (
                {field: entry.get(field) for field in PUBLIC_SOURCE_HASH_FIELDS}
                for entry in unsorted_dict.get("public_sources") or []
            ),
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
