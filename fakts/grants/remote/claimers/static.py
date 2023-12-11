from pydantic import Field
from typing import Any, Dict
from fakts.grants.remote.types import FaktsEndpoint, FaktsRequest, FaktValue
from pydantic import BaseModel


class StaticClaimer(BaseModel):
    """A claimer that always claims
    the same configuration

    This is mostly used for testing purposes.

    """

    value: Dict[str, Any] = Field(
        default_factory=lambda: {},
        exclude=True,
    )
    """ An ssl context to use for the connection to the endpoint"""

    async def aclaim(
        self, token: str, endpoint: FaktsEndpoint, request: FaktsRequest
    ) -> Dict[str, FaktValue]:
        """Claim the configuration from the endpoint"""

        return self.value
