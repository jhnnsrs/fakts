"""The headless grant: log in with a standing mandate key.

Used where no human is available: CI runners, deployed containers, the apps a
hub or a deployer runs. A mandate is an authority someone granted in advance;
whoever holds its key logs this app in as them.

There is no refresh token: the server answers with an access token only, and
the client runs the grant again when it expires (:meth:`MandateKeyAuthorizer.arenew`).
Every run is checked against the mandate, so a revoked key stops working within
one access-token lifetime.

The manifest is encoded as a JSON *string* in a form field here, unlike the
device authorization request which takes it as a nested JSON object. That
asymmetry is the server's, not ours.
"""

import json
from enum import Enum

from pydantic import BaseModel, SecretStr

from fakts import oauth2
from fakts.errors import NeedsReauthenticationError
from fakts.grants.remote.errors import RetrieveError
from fakts.grants.remote.models import FaktsEndpoint, SSLContextModel
from fakts.oauth2 import TokenResponse

from .device_code import ClientRole


class HeadlessClientKind(str, Enum):
    """The kinds of client a mandate key may log in."""

    DEVELOPMENT = "development"
    DESKTOP = "desktop"
    MOBILE = "mobile"


class MandateKeyAuthorizer(SSLContextModel):
    """Logs in with a mandate key, and logs in again whenever the access token runs out."""

    manifest: BaseModel
    key: SecretStr
    """The mandate key (``FAKTS_MANDATE_KEY``)."""
    requested_client_kind: HeadlessClientKind = HeadlessClientKind.DEVELOPMENT
    requested_client_role: ClientRole = ClientRole.INTERFACE
    request_auth_key: bool = False
    """Ask for a mesh key on the first login (the mandate must allow it). Renewals never ask."""
    allow_insecure_transport: bool = False

    requires_user_interaction: bool = False
    """No human is involved, so running the grant again unattended is safe."""

    async def _alogin(self, token_endpoint: str, *, request_auth_key: bool) -> TokenResponse:
        try:
            data = await oauth2.apost_form(
                token_endpoint,
                {
                    "grant_type": oauth2.MANDATE_KEY_GRANT,
                    "key": self.key.get_secret_value(),
                    "manifest": json.dumps(self.manifest.model_dump()),
                    "requested_client_kind": self.requested_client_kind.value,
                    "requested_client_role": self.requested_client_role.value,
                    "request_auth_key": "true" if request_auth_key else "false",
                },
                ssl_context=self.ssl_context,
                allow_insecure_transport=self.allow_insecure_transport,
            )
        except oauth2.OAuth2ErrorResponse as e:
            if e.error == "invalid_grant":
                raise NeedsReauthenticationError(
                    f"The server refused the mandate key: {(e.description or e.error).rstrip('.')}. "
                    f"It was revoked, has expired, or does not cover this app; ask for a new one."
                ) from e
            raise RetrieveError(f"The server refused the mandate-key login: {e}") from e
        return oauth2.parse_token_response(data, token_endpoint)

    async def aauthorize(self, endpoint: FaktsEndpoint) -> TokenResponse:
        if not endpoint.token_endpoint:
            raise RetrieveError(f"{endpoint.name} advertised no token_endpoint to log in at.")
        return await self._alogin(
            str(endpoint.token_endpoint), request_auth_key=self.request_auth_key
        )

    async def arenew(self, token_endpoint: str) -> TokenResponse:
        """Log in again for a fresh access token (and a freshly rendered envelope)."""
        return await self._alogin(token_endpoint, request_auth_key=False)
