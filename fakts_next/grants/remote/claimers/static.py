from pydantic import Field
from fakts_next.grants.remote.models import FaktsEndpoint, ActiveFakts
from pydantic import BaseModel


class StaticClaimer(BaseModel):
    """A claimer that always claims
    the same configuration

    This is mostly used for testing purposes.

    """

    value: ActiveFakts = Field(
        exclude=True,
    )
    """ An ssl context to use for the connection to the endpoint"""

    async def aclaim(
        self,
        token: str,
        endpoint: FaktsEndpoint,
    ) -> ActiveFakts:
        """Claim the configuration from the endpoint"""

        return self.value
