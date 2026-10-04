"""The interactive grant: RFC 8628 device authorization, fakts-flavoured.

Two requests, one human in between:

1. ``POST {device_authorization_endpoint}`` with the app's manifest. The
   server registers a public client for the app, stages a device code, and
   answers with a ``user_code`` plus a ready-made approval URL.
2. ``POST {token_endpoint}`` in a polling loop until the user approves,
   declines, or the code expires.

Only the second half is standard OAuth. The first is where fakts extends
the protocol, because OAuth has no slot for "here is what my app needs, ask
the user which parts to grant".
"""

import asyncio
import dataclasses
import logging
import time
import webbrowser
from collections.abc import Awaitable, Callable
from enum import Enum
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, Field, model_validator

from fakts import oauth2
from fakts.grants.remote.errors import (
    DeviceCodeError,
    DeviceCodeExpiredError,
    DeviceCodeTimeoutError,
    UserDeniedError,
)
from fakts.grants.remote.models import FaktsEndpoint, SSLContextModel
from fakts.oauth2 import TokenResponse

from .utils import print_device_code_prompt, print_succesfull_login

logger = logging.getLogger(__name__)


def _as_seconds(raw: object, default: int, field: str) -> int:
    """Read a server-supplied duration, or fail as a DeviceCodeError.

    ``int(raw)`` straight off the wire lets a malformed value surface as a
    bare ValueError from the middle of the flow, which reads like a client
    bug rather than what it is: the endpoint sent us nonsense.
    """
    if raw is None:
        return default
    try:
        return int(raw)  # type: ignore[call-overload]
    except (TypeError, ValueError) as e:
        raise DeviceCodeError(
            f"The device authorization endpoint sent a non-numeric '{field}': {raw!r}."
        ) from e


@dataclasses.dataclass(frozen=True)
class DeviceCodeChallenge:
    """What a person needs to approve a login: handed to the device-code hook."""

    endpoint: FaktsEndpoint
    """The server being logged in to."""
    user_code: str
    """The code to enter on the approval page."""
    verification_uri_complete: str
    """The approval page with the code already entered: the link to show or open."""
    expires_in: int
    """Seconds until the code stops being accepted."""


DeviceCodeHook = Callable[[DeviceCodeChallenge], Awaitable[None]]
GrantedHook = Callable[["FaktsEndpoint", str], Awaitable[None]]


async def display_in_terminal(challenge: DeviceCodeChallenge) -> None:
    """The default device code hook: print the approval page and the code."""
    print_device_code_prompt(
        challenge.verification_uri_complete,
        challenge.endpoint.base_url,
        challenge.user_code,
    )


async def granted_in_terminal(endpoint: "FaktsEndpoint", token: str) -> None:
    """A default hook that is called when the device code is granted"""
    print_succesfull_login()


class ClientKind(str, Enum):
    """What sort of client is asking. The server renders consent differently
    per kind, and binds the resulting client accordingly."""

    DEVELOPMENT = "development"
    WEBSITE = "website"
    DESKTOP = "desktop"
    HUB = "hub"
    RELYING_PARTY = "relying_party"


class ClientRole(str, Enum):
    """Whether the app drives a user interface or acts on its own behalf."""

    INTERFACE = "interface"
    AGENT = "agent"


class DeviceCodeAuthorizer(SSLContextModel):
    """Negotiates a session by asking a human to approve the app once."""

    manifest: BaseModel
    """The app's manifest. Sent as a nested JSON object, and rendered on the
    consent screen — including individually declinable optional
    requirements."""

    device_code_hook: DeviceCodeHook = Field(default=display_in_terminal, exclude=True)
    """Called with the challenge once the server has staged it: the code and
    the link a person approves it at. A host shows them in its own interface;
    tests and headless harnesses approve out of band."""
    granted_hook: GrantedHook = Field(default=granted_in_terminal, exclude=True)

    expiration_time_seconds: int = 300
    """How long the device code should stay valid. The server clamps this to
    its own maximum, so the returned ``expires_in`` may be shorter."""
    redirect_uris: list[str] = Field(default_factory=list)
    requested_client_kind: ClientKind = ClientKind.DEVELOPMENT
    requested_client_role: ClientRole = ClientRole.INTERFACE
    timeout: float | None = None
    """The client's own deadline. ``None`` means "trust the server's
    ``expires_in``"."""
    open_browser: bool = True
    allow_insecure_transport: bool = False
    request_auth_key: bool = False
    """Ask for a key to join the deployment's mesh; it comes back once, with
    the first token (as ``mesh``), if the approver allows it."""

    sleeper: Callable[[float], Awaitable[None]] = Field(default=asyncio.sleep, exclude=True)
    """Injected so tests can assert the polling cadence without spending it."""

    requires_user_interaction: bool = True

    @model_validator(mode="after")
    def _check_manifest(self) -> "DeviceCodeAuthorizer":
        if not hasattr(self.manifest, "model_dump"):
            raise ValueError("manifest must be a pydantic model")
        return self

    async def arequest_code(self, endpoint: FaktsEndpoint) -> dict:
        """Stage a device code and register a client for this app."""
        if not endpoint.device_authorization_endpoint:
            raise DeviceCodeError(
                f"{endpoint.name} did not advertise a device_authorization_endpoint. "
                f"A fakts protocol v2 server must publish one."
            )

        payload = {
            "manifest": self.manifest.model_dump(),
            "expiration_time_seconds": self.expiration_time_seconds,
            "redirect_uris": self.redirect_uris,
            "requested_client_kind": self.requested_client_kind.value,
            "requested_client_role": self.requested_client_role.value,
        }
        if self.request_auth_key:
            payload["request_auth_key"] = True

        return await oauth2.apost_json(
            endpoint.device_authorization_endpoint,
            payload,
            ssl_context=self.ssl_context,
            allow_insecure_transport=self.allow_insecure_transport,
        )

    async def aauthorize(self, endpoint: FaktsEndpoint) -> TokenResponse:
        """Run the full device flow and return the resulting session."""
        started = await self.arequest_code(endpoint)

        device_code = started.get("device_code")
        user_code = started.get("user_code")
        client_id = started.get("client_id")
        if not device_code or not client_id:
            raise DeviceCodeError(
                f"{endpoint.name} answered the device authorization request without "
                f"a device_code and client_id (it sent: {sorted(started)})"
            )

        # The server hands back a complete approval URL; opening anything we
        # derived ourselves would only reintroduce guesswork.
        verification_uri = started.get("verification_uri_complete") or started.get(
            "verification_uri"
        )
        if self.open_browser and verification_uri:
            # The URL comes from the server, and webbrowser hands unknown
            # schemes to the desktop's handler — so a hostile endpoint could
            # otherwise get `file://` or a registered custom scheme invoked.
            scheme = urlparse(verification_uri).scheme.lower()
            if scheme in ("http", "https"):
                webbrowser.open_new(verification_uri)
            else:
                logger.warning(
                    "Refusing to open %r: the approval URL must be http or https.",
                    verification_uri,
                )

        expires_in = _as_seconds(
            started.get("expires_in"), self.expiration_time_seconds, "expires_in"
        )
        if user_code:
            await self.device_code_hook(
                DeviceCodeChallenge(
                    endpoint=endpoint,
                    user_code=user_code,
                    # `configure` is a template with a literal {code}: the fallback
                    # for a server that sent no complete link of its own.
                    verification_uri_complete=verification_uri
                    or (endpoint.configure or "").replace("{code}", user_code)
                    or endpoint.base_url,
                    expires_in=expires_in,
                )
            )

        # Poll the endpoint the session will be renewed against, not one the
        # device response names: the two must never diverge.
        token_endpoint = endpoint.token_endpoint
        if not token_endpoint:
            raise DeviceCodeError(f"{endpoint.name} advertised no token_endpoint to poll.")

        response = await self._apoll(
            token_endpoint,
            device_code=device_code,
            client_id=client_id,
            interval=_as_seconds(started.get("interval"), 5, "interval"),
            expires_in=expires_in,
        )

        await self.granted_hook(endpoint, response.access_token)
        return response

    async def _apoll(
        self,
        token_endpoint: str,
        *,
        device_code: str,
        client_id: str,
        interval: int,
        expires_in: int,
    ) -> TokenResponse:
        """Poll the token endpoint until the user decides.

        The RFC 8628 error codes replace v1's bespoke status envelope:
        ``authorization_pending`` means keep waiting, ``slow_down`` means we
        are being too eager, and the other two are terminal.
        """
        budget = self.timeout if self.timeout is not None else expires_in
        # Measure real elapsed time, not the sum of the sleeps. Counting only
        # the sleeps ignores the round trips entirely, so against a server
        # that accepts the connection and stalls, a nominal five-minute
        # deadline would take hours to fire.
        deadline = time.monotonic() + budget

        # A server answering `interval: 0` would otherwise get an
        # un-throttled poll loop.
        interval = max(1, interval)

        while time.monotonic() < deadline:
            await self.sleeper(interval)

            try:
                data = await oauth2.apost_form(
                    token_endpoint,
                    {
                        "grant_type": oauth2.DEVICE_CODE_GRANT,
                        "device_code": device_code,
                        "client_id": client_id,
                    },
                    ssl_context=self.ssl_context,
                    allow_insecure_transport=self.allow_insecure_transport,
                )
            except (aiohttp.ClientError, TimeoutError, oauth2.TransientHTTPError) as e:
                # The user may be halfway through approving: one dropped
                # connection or 5xx must not end the login. The deadline
                # still bounds how long this keeps trying.
                logger.info("Polling %s failed (%s); retrying.", token_endpoint, e)
                continue
            except oauth2.OAuth2ErrorResponse as e:
                if e.error == "authorization_pending":
                    continue
                if e.error == "slow_down":
                    # Never let the throttle grow past what is left of the
                    # budget. Unbounded, a server that keeps answering
                    # slow_down pushes a single sleep beyond the deadline, so
                    # the loop ends in a timeout having quietly stopped asking
                    # somewhere in the middle.
                    remaining = deadline - time.monotonic()
                    interval = min(interval + 5, max(1, int(remaining)))
                    continue
                if e.error == "access_denied":
                    raise UserDeniedError("The user declined to grant this app access.") from e
                if e.error == "expired_token":
                    raise DeviceCodeExpiredError(
                        "The device code expired before it was approved."
                    ) from e
                raise DeviceCodeError(f"The token endpoint refused the device code: {e}") from e

            return oauth2.parse_token_response(data, token_endpoint)

        raise DeviceCodeTimeoutError(
            f"Gave up waiting for the device code to be approved after {budget}s."
        )
