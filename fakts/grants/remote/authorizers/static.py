"""The pre-issued-credential grant: skip negotiation entirely.

For callers that already hold a credential from an earlier session and just
want to resume it — the deployer path, and tests.

A refresh token alone is *not* a usable credential. The token endpoint
authenticates the client before it looks at the refresh token, and then
checks the token actually belongs to that client, so the ``client_id`` has
to travel with it. Hence the compound ``client_id:refresh_token`` form.
"""

from typing import Tuple

from fakts import oauth2
from fakts.grants.remote.errors import RetrieveError
from fakts.grants.remote.models import FaktsEndpoint, SSLContextModel
from fakts.oauth2 import TokenResponse


def split_credential(value: str) -> Tuple[str, str]:
    """Split a ``client_id:refresh_token`` pair.

    Split once from the left: refresh tokens are URL-safe base64 and never
    contain a colon, so the first one is unambiguously the separator.
    """
    client_id, separator, refresh_token = value.partition(":")
    if not separator or not client_id or not refresh_token:
        raise RetrieveError(
            "Expected a credential of the form 'client_id:refresh_token', got "
            f"{value[:12]!r}... A bare refresh token is not enough: the token "
            "endpoint authenticates the client before it validates the token."
        )
    return client_id, refresh_token


class StaticAuthorizer(SSLContextModel):
    """Resumes a session from a credential handed in from outside."""

    token: str
    """A ``client_id:refresh_token`` pair."""
    allow_insecure_transport: bool = False

    requires_user_interaction: bool = False

    async def aauthorize(self, endpoint: FaktsEndpoint) -> TokenResponse:
        if not endpoint.token_endpoint:
            raise RetrieveError(
                f"{endpoint.name} advertised no token_endpoint to refresh against."
            )

        client_id, refresh_token = split_credential(self.token)

        try:
            data = await oauth2.apost_form(
                endpoint.token_endpoint,
                {
                    "grant_type": oauth2.REFRESH_GRANT,
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                },
                ssl_context=self.ssl_context,
                allow_insecure_transport=self.allow_insecure_transport,
            )
        except oauth2.OAuth2ErrorResponse as e:
            raise RetrieveError(
                f"{endpoint.name} refused the supplied credential: {e}. Refresh "
                f"tokens rotate on every use, so a credential captured from an "
                f"earlier session may already have been superseded."
            ) from e

        data.setdefault("client_id", client_id)
        return TokenResponse(**data)
