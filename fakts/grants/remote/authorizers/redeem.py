"""The headless grant: trade a provisioning token for a session.

Used where no human is available — CI runners, deployed containers, the
app deployer. Under protocol v2 this is an OAuth extension grant at the
token endpoint rather than a bespoke endpoint of its own.

Note the manifest is encoded as a JSON *string* in a form field here, unlike
the device authorization request which takes it as a nested JSON object.
That asymmetry is the server's, not ours.
"""

import json
from typing import Optional

from pydantic import BaseModel

from fakts import oauth2
from fakts.grants.remote.errors import RetrieveError
from fakts.grants.remote.models import FaktsEndpoint, SSLContextModel
from fakts.oauth2 import TokenResponse

from .device_code import ClientRole


class RedeemAuthorizer(SSLContextModel):
    """Exchanges a pre-issued redeem token for a live session."""

    manifest: BaseModel
    token: str
    """The redeem token. Servers may mint these single-use, in which case a
    session that lapses past the refresh window cannot be recovered without
    re-provisioning."""
    requested_client_role: ClientRole = ClientRole.INTERFACE
    allow_insecure_transport: bool = False

    requires_user_interaction: bool = False
    """No human is involved, so an unattended re-run is safe — this is what
    lets long-lived deployments recover from an expired refresh chain."""

    async def aauthorize(self, endpoint: FaktsEndpoint) -> TokenResponse:
        if not endpoint.token_endpoint:
            raise RetrieveError(
                f"{endpoint.name} advertised no token_endpoint to redeem against."
            )

        try:
            data = await oauth2.apost_form(
                endpoint.token_endpoint,
                {
                    "grant_type": oauth2.REDEEM_GRANT,
                    "redeem_token": self.token,
                    "manifest": json.dumps(self.manifest.model_dump()),
                    "requested_client_role": self.requested_client_role.value,
                },
                ssl_context=self.ssl_context,
                allow_insecure_transport=self.allow_insecure_transport,
            )
        except oauth2.OAuth2ErrorResponse as e:
            raise RetrieveError(
                f"{endpoint.name} refused the redeem token: {e}. Redeem tokens are "
                f"often single-use and may already have been spent or expired."
            ) from e

        return TokenResponse(**data)
