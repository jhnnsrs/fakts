from fakts.grants.errors import GrantError
from typing import Dict
import logging
from .types import Demander, Discovery, Claimer
from fakts.types import FaktsRequest, FaktValue
from pydantic import BaseModel

logger = logging.getLogger(__name__)


Token = str
EndpointUrl = str


class RemoteGrantError(GrantError):
    """Base class for all remotegrant errors"""


class RemoteGrant(BaseModel):
    """Abstract base class for remote grants

    A Remote grant is a grant that connects to a fakts server,
    and tires to establishes a secure relationship with it.

    This is a highly configurable grant, that can be used to
    dynaimcially *discover* the endpoint, *demand* a token
    to access a token, and then *claim* the configuration
    from the endpoint.

    This grant is highly configurable, and can be used to
    implement any kind of remote grant.

    You can use a specific builder to build a remote grant
    that fits your needs.
    """

    discovery: Discovery
    """The discovery mechanism to use for finding the endpoint"""

    demander: Demander
    """The demander mechanism to use for demanding the token FROM the endpoint"""

    claimer: Claimer
    """The claimer mechanism to use for claiming the token FROM the endpoint"""

    async def aload(self, request: FaktsRequest) -> Dict[str, FaktValue]:
        """Load the configuration

        This function will first discover the endpoint, then demand a token from it,
        and then claim the configuration from it.

        Parameters
        ----------
        request : FaktsRequest
            The request to use for the load

        Returns
        -------
        Dict[str, FaktValue]
            The configuration that was claimed from the endpoint



        """
        endpoint = await self.discovery.adiscover(request)
        token = await self.demander.ademand(endpoint, request)

        return await self.claimer.aclaim(token, endpoint, request)

    class Config:
        """A pydantic config class for the RemoteGrant"""

        arbitrary_types_allowed = True
