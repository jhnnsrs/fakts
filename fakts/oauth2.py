"""The OAuth2 wire layer shared by the runtime token path and the authorizers.

Protocol v2 speaks standard OAuth 2.0: a device authorization grant
(RFC 8628) to get started, then the refresh grant (RFC 6749 §6) forever
after. What stays fakts-specific rides along as extension members on
otherwise ordinary token responses.

This module exists so that :mod:`fakts.fakts` can renew a token without
importing ``fakts.grants.remote.*`` — the runtime path and the
negotiation path need the same primitives but must not depend on each other.

We deliberately hand-roll this rather than use ``oauthlib``:

- ``parse_request_body_response`` raises a bare :class:`Warning` when the
  granted scope differs from the requested one. Under per-requirement
  consent that is the *normal* case, not an anomaly.
- RFC 8628 error codes (``authorization_pending``, ``slow_down``) never
  resolve to their typed classes, because ``raise_from_error`` only scans
  the RFC 6749 error module. The device state machine would have to
  string-match anyway.
- ``prepare_refresh_token_request`` rejects ``http://localhost`` outright,
  which is this package's primary development target.

What is left is a few dozen lines, and they are clearer standing alone.
"""

import json
import logging
import os
import ssl
import time
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, Field

from fakts.errors import FaktsError
from fakts.models import ActiveFakts, AuthFakt, GrantStatus, Instance, SelfFakt

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT = 30
"""Seconds to allow a single OAuth2 request.

aiohttp's own default is 300s. That is not a timeout so much as a hang: a
token endpoint that accepts the connection and then stalls would block
``aget_token()`` — and anything waiting on it — for five minutes."""

TOKEN_EXPIRY_SKEW = 30
"""Seconds before the actual expiry at which a token is considered expired.

Lives here because :func:`resolve_expiry` is what applies (and clamps) it.
It used to be declared independently in both ``fakts.py`` and
``grants/remote/base.py``, with nothing keeping the two in step."""

DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
"""RFC 8628 device authorization grant."""

REDEEM_GRANT = "urn:fakts:grant-type:redeem"
"""The fakts extension grant that trades a provisioning token for a session.
Note the URN has no ``params:oauth`` segment — it is a fakts URN, not an
IETF one."""

REFRESH_GRANT = "refresh_token"

INSECURE_TRANSPORT_ENV = "FAKTS_ALLOW_INSECURE_TRANSPORT"
"""Environment opt-in for containers that cannot pass a keyword argument."""

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

_warned_insecure_hosts: set[str] = set()


class InsecureTransportError(FaktsError):
    """Raised when credentials would travel over plain HTTP unasked.

    Plain HTTP against a network host is a supported fakts deployment mode,
    but it has to be chosen rather than stumbled into — v2 puts a rotating
    refresh token on the wire where v1 put a configuration blob.
    """


class OAuth2ErrorResponse(Exception):
    """A structured OAuth2 error response (RFC 6749 §5.2).

    Carries the machine-readable ``error`` code so callers can drive a state
    machine off it — ``authorization_pending`` and ``slow_down`` are normal
    control flow during device polling, not failures.
    """

    def __init__(
        self,
        error: str,
        description: Optional[str] = None,
        status: Optional[int] = None,
    ) -> None:
        self.error = error
        self.description = description
        self.status = status
        super().__init__(
            f"{error}: {description}" if description else error,
        )


class TokenResponse(BaseModel):
    """A successful token response, plus the fakts extension members.

    The server merges ``self`` / ``instances`` / ``statuses`` into the token
    response for every grant that belongs to an app client, and re-renders
    them on *every* refresh — aliases are host-aware, so configuration drift
    propagates without re-approval.
    """

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    scope: Optional[str] = None
    client_id: Optional[str] = None

    self_: Optional[SelfFakt] = Field(default=None, alias="self")
    instances: Dict[str, Instance] = Field(default_factory=dict)
    statuses: Dict[str, GrantStatus] = Field(default_factory=dict)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @property
    def scopes(self) -> list[str]:
        """The *granted* scopes. Never compare these against what was asked
        for: declining an optional requirement legitimately narrows them."""
        return self.scope.split(" ") if self.scope else []


def is_loopback(url: str) -> bool:
    """Whether ``url`` addresses this machine.

    Loopback plain-HTTP is always allowed, matching the server's own rule
    (authlib's ``is_secure_transport``) so that local development needs no
    opt-in on either side.
    """
    host = (urlparse(url).hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def check_transport(url: str, allow_insecure: bool) -> None:
    """Gate a *credential-bearing* request on the transport opt-in.

    Discovery is deliberately not gated: it carries no secret, and a
    downgraded discovery yields a plain-HTTP token endpoint that this check
    catches anyway. The gate belongs where the credential is, not where the
    URL was learned.
    """
    if urlparse(url).scheme != "http" or is_loopback(url):
        return

    if not (allow_insecure or _env_opt_in()):
        raise InsecureTransportError(
            f"Refusing to send OAuth2 credentials over plain HTTP to {url}. "
            f"Fakts supports plain HTTP on network hosts, but it must be opted "
            f"into: pass allow_insecure_transport=True to the builder, or set "
            f"{INSECURE_TRANSPORT_ENV}=1. Use https:// instead if this "
            f"deployment terminates TLS."
        )

    host = urlparse(url).netloc
    if host not in _warned_insecure_hosts:
        _warned_insecure_hosts.add(host)
        logger.warning(
            "Sending OAuth2 credentials over plain HTTP to %s. This was "
            "explicitly allowed; anyone on the path can read the refresh token.",
            host,
        )


def _env_opt_in() -> bool:
    """Whether the environment opts in to plain-HTTP credentials.

    Truthiness alone would make ``FAKTS_ALLOW_INSECURE_TRANSPORT=0`` *enable*
    the thing it looks like it disables.
    """
    raw = os.environ.get(INSECURE_TRANSPORT_ENV)
    if raw is None:
        return False
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _connector(ssl_context: ssl.SSLContext) -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(ssl=ssl_context)


async def _handle(response: aiohttp.ClientResponse, url: str) -> Dict[str, Any]:
    """Parse an OAuth2 response body, raising :class:`OAuth2ErrorResponse`.

    Two shapes have to be tolerated beyond plain RFC 6749: the fakts device
    authorization endpoint answers ``200`` with ``{"status": "error"}``, and
    its throttle answers ``429`` with a bare ``{"error": "slow_down"}`` and
    no ``status`` key at all.
    """
    text = await response.text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise FaktsError(
            f"{url} did not answer with JSON (status {response.status}): "
            f"{text[:200]}"
        ) from e

    if not isinstance(data, dict):
        raise FaktsError(f"{url} answered with {type(data).__name__}, expected an object")

    if "error" in data and data.get("error"):
        raise OAuth2ErrorResponse(
            str(data["error"]),
            data.get("error_description"),
            response.status,
        )

    # The fakts device endpoint signals failure inside a 200 body.
    if data.get("status") == "error":
        raise FaktsError(f"{url} rejected the request: {data.get('error', 'unknown error')}")

    if response.status >= 400:
        raise FaktsError(f"{url} answered {response.status}: {text[:200]}")

    return data


async def apost_form(
    url: str,
    data: Mapping[str, str],
    *,
    ssl_context: ssl.SSLContext,
    allow_insecure_transport: bool = False,
    bearer: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """POST ``application/x-www-form-urlencoded`` to an OAuth2 endpoint."""
    check_transport(url, allow_insecure_transport)
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    async with aiohttp.ClientSession(
        connector=_connector(ssl_context),
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as session:
        async with session.post(url, data=dict(data), headers=headers) as response:
            return await _handle(response, url)


async def apost_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    ssl_context: ssl.SSLContext,
    allow_insecure_transport: bool = False,
    bearer: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """POST a JSON body.

    The device authorization endpoint takes JSON with a *nested* manifest
    object, while the redeem grant takes form data with the manifest as a
    JSON *string*. They are genuinely different encodings.
    """
    check_transport(url, allow_insecure_transport)
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    async with aiohttp.ClientSession(
        connector=_connector(ssl_context),
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as session:
        async with session.post(url, json=dict(payload), headers=headers) as response:
            return await _handle(response, url)


def resolve_expiry(expires_in: Optional[int], skew: int, now: Optional[float] = None) -> Optional[float]:
    """Turn ``expires_in`` into an absolute timestamp.

    Three cases, all of which have bitten someone:

    - **absent** → ``None``. The server declared no lifetime, so treat the
      token as opaque and refresh only when it is rejected.
    - **<= 0** → already expired. A server that says this is misbehaving,
      but pretending the token is eternal would be worse.
    - otherwise → ``now + expires_in``, with the safety skew *clamped* to
      half the lifetime. Clamping matters: a genuine 20-second token must
      not be treated as never-expiring just because the skew exceeds it,
      and it must not be treated as already-expired either, which would
      turn every single token fetch into a round-trip.
    """
    if expires_in is None:
        return None

    now = time.time() if now is None else now
    if expires_in <= 0:
        logger.error(
            "Token endpoint returned expires_in=%s; treating the access token as "
            "already expired. This is a server-side bug.",
            expires_in,
        )
        return now

    return now + expires_in - min(skew, expires_in / 2)


def merge_token_response(
    previous: Optional[ActiveFakts],
    response: TokenResponse,
    *,
    token_endpoint: str,
    report_endpoint: Optional[str],
    skew: int,
    fallback_client_id: Optional[str] = None,
) -> ActiveFakts:
    """Build a *new* :class:`ActiveFakts` from a token response.

    Never mutates ``previous``: a rotation has to be persisted before it is
    committed to memory, and that is only safe if the candidate and the
    current state are distinct objects.

    ``self`` and ``statuses`` are adopted wholesale, but ``instances`` is
    *merged* — :meth:`Fakts.arefresh_aliases` reorders each instance's alias
    list to put the last known-good route first, and adopting the server's
    ordering hourly would silently destroy that optimization.
    """
    now = time.time()

    client_id = response.client_id or fallback_client_id
    if not client_id:
        raise FaktsError(
            "The token response carried no client_id and none was remembered from "
            "the authorization step. The client cannot refresh without one."
        )

    refresh_token = response.refresh_token or (
        previous.auth.refresh_token if previous else None
    )
    if not refresh_token:
        raise FaktsError(
            "The token response carried no refresh_token. fakts protocol v2 is "
            "refresh-token based and cannot maintain a session without one."
        )

    rotated = previous is None or previous.auth.refresh_token != refresh_token
    chain_started_at = (
        previous.auth.chain_started_at if previous and previous.auth.chain_started_at else now
    )

    auth = AuthFakt(
        client_id=client_id,
        token_endpoint=token_endpoint,
        report_endpoint=report_endpoint,
        scopes=response.scopes or (previous.auth.scopes if previous else []),
        refresh_token=refresh_token,
        access_token=response.access_token,
        expires_at=resolve_expiry(response.expires_in, skew, now),
        refresh_issued_at=now if rotated else (previous.auth.refresh_issued_at if previous else now),
        chain_started_at=chain_started_at,
        token_type=response.token_type or "Bearer",
    )

    instances = _merge_instances(previous.instances if previous else {}, response.instances)

    self_fakt = response.self_ or (previous.self if previous else None)
    if self_fakt is None:
        raise FaktsError(
            "The token response carried no 'self' block and none was cached. The "
            "client cannot identify the deployment it is talking to."
        )

    return ActiveFakts(
        self=self_fakt,
        auth=auth,
        instances=instances,
        statuses=response.statuses if response.statuses else (previous.statuses if previous else {}),
    )


def _merge_instances(
    previous: Mapping[str, Instance], incoming: Mapping[str, Instance]
) -> Dict[str, Instance]:
    """Adopt the server's instances while keeping the learned alias order.

    The server is authoritative about *which* aliases exist; the client is
    authoritative about which one worked last time. Preserve the local
    ordering for aliases that survive, and append genuinely new ones.
    """
    if not incoming:
        return dict(previous)

    merged: Dict[str, Instance] = {}
    for key, instance in incoming.items():
        old = previous.get(key)
        if old is None or not old.aliases:
            merged[key] = instance
            continue

        preference = {alias.id: index for index, alias in enumerate(old.aliases)}
        reordered = sorted(
            instance.aliases,
            key=lambda alias: preference.get(alias.id, len(preference)),
        )
        merged[key] = instance.model_copy(update={"aliases": reordered})

    return merged


def instances_changed(previous: Optional[ActiveFakts], candidate: ActiveFakts) -> bool:
    """Whether the set of reachable services materially changed.

    Used to invalidate resolved aliases after a refresh: a re-approval that
    *reduces* the grant would otherwise leave the client happily talking to
    a service it no longer has access to.
    """
    if previous is None:
        return True
    if set(previous.instances) != set(candidate.instances):
        return True
    return any(
        {alias.id for alias in previous.instances[key].aliases}
        != {alias.id for alias in candidate.instances[key].aliases}
        for key in previous.instances
    )
