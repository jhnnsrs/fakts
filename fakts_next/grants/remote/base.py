import logging

from pydantic import BaseModel, ConfigDict

from fakts_next.models import ActiveFakts
from fakts_next.oauth2 import TOKEN_EXPIRY_SKEW, merge_token_response

from .errors import RemoteGrantError
from .models import Authorizer, Discovery

logger = logging.getLogger(__name__)


class RemoteGrant(BaseModel):
    """Obtains configuration by negotiating an OAuth2 session with a server.

    Two steps under protocol v2, where v1 had three: *discover* the endpoint,
    then *authorize* against it. The old "claim" step is gone — the token
    endpoint returns the tokens and the configuration together, so there is
    no separate artifact to trade.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    discovery: Discovery
    """The discovery mechanism to use for finding the endpoint"""

    authorizer: Authorizer
    """The grant to run against the discovered endpoint."""

    @property
    def requires_user_interaction(self) -> bool:
        """Whether reloading this grant would put a browser in front of a user."""
        return getattr(self.authorizer, "requires_user_interaction", True)

    async def aload(self) -> ActiveFakts:
        """Discover an endpoint, authorize against it, assemble the config.

        The client assembles :class:`ActiveFakts` itself now: the endpoint
        metadata supplies the token and report URLs, and the token response
        supplies the credentials and the service instances. The server no
        longer sends an ``auth`` block at all.
        """
        try:
            endpoint = await self.discovery.adiscover()
        except Exception as e:
            raise RemoteGrantError(
                f"Could not discover the Fakts endpoint using "
                f"{self.discovery.__class__.__name__}: {e}"
            ) from e

        response = await self.authorizer.aauthorize(endpoint)

        if not endpoint.token_endpoint:
            raise RemoteGrantError(
                f"{endpoint.name} advertised no token_endpoint, so the session "
                f"could not be renewed later."
            )

        return merge_token_response(
            None,
            response,
            token_endpoint=endpoint.token_endpoint,
            report_endpoint=endpoint.report_endpoint,
            skew=TOKEN_EXPIRY_SKEW,
        )
