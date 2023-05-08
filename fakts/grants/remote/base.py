from pydantic import Field
from fakts.discovery.base import Discovery
from fakts.discovery.static import StaticDiscovery
from fakts.discovery.base import FaktsEndpoint
from fakts.grants.base import FaktsGrant
from fakts.grants.errors import GrantError
import ssl
import certifi
from pydantic import BaseModel
import aiohttp
from typing import Any, Dict, Optional, List
from .errors import ClaimError
import logging

logger = logging.getLogger(__name__)


Token = str
EndpointUrl = str


class FaktClaim(BaseModel):
    """FaktClaim

    A FaktClaim is a claim for a Fakt. It is used to claim a Fakt on a Fakts endpoint.

    """

    version: str
    identifier: str
    endpoint_url: str
    token: str


class CacheFile(BaseModel):
    """Cache file model"""

    claims: Dict[EndpointUrl, FaktClaim]


class Manifest(BaseModel):
    version: str
    identifier: str
    scopes: List[str]
    logo: Optional[str]
    """ Scopes that this app should request from the user """

    class Config:
        extra = "forbid"


class RemoteGrantError(GrantError):
    """Base class for all remotegrant errors"""


class RemoteGrant(FaktsGrant):
    """Abstract base class for remote grants

    A Remote grant is a grant that connects to a fakts server,
    and tires to establishes a secure relationship with it.

    This is done by providing the fakts server with a software
    manifest consisting of a world unique identifier, and a
    version number.

    The fakts server then can depending on the grant type
    respond with a token that then in turn can be used to
    retrieve the configuration from the fakts server.

    """

    discovery: Discovery = Field(default_factory=StaticDiscovery)
    "The discovery method to use, if not specified, the static discovery will be used"

    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    """ An ssl context to use for the connection to the endpoint"""

    auto_demand_on_failure: bool = True
    """ If set to true, the grant will try to demand a new token if the claim fails"""

    force_refresh: bool = False
    """Should we always force a refresh of the token. If we have no cached it?"""

    async def aload(self, force_refresh: bool = False):
        """Load the configuration from the remote endpoint

        This function will load the configuration from the remote endpoint.
        It will first try to load the configuration from the cache file.
        If this fails, it will try to load the configuration from the endpoint.
        If this fails, it will try to demand a new token from the endpoint.
        If this fails, it will raise an exception.

        """
        endpoint = await self.discovery.discover()
        token = await self.ademand(endpoint)

        return await self.aclaim(token, endpoint)

    async def ademand(self, endpoint: FaktsEndpoint) -> Token:
        """Demand a token for receiving the configuration, for this
        specific app"""

        raise NotImplementedError(
            "This is an abstract base Class. Please use one of the subclasses"
        )

    async def aclaim(self, token: Token, endpoint: FaktsEndpoint) -> Dict[str, Any]:
        """Claim the configuration from the endpoint"""

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self.ssl_context)
        ) as session:
            async with session.post(
                f"{endpoint.base_url}claim/",
                json={
                    "token": token,
                },
            ) as resp:
                data = await resp.json()

                if resp.status == 200:
                    data = await resp.json()
                    if not "status" in data:
                        raise ClaimError("Malformed Answer")

                    status = data["status"]
                    if status == "error":
                        raise ClaimError(data["message"])
                    if status == "granted":
                        return data["config"]

                    raise ClaimError(f"Unexpected status: {status}")
                else:
                    raise Exception("Error! Coud not claim this app on this endpoint")

    class Config:
        arbitrary_types_allowed = True
