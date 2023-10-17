from pydantic import Field
from fakts.grants.base import FaktsGrant
from fakts.grants.errors import GrantError
import ssl
import certifi
import aiohttp
from typing import Any, Dict
from .errors import ClaimError
import logging
from .types import Demander, Discovery, FaktsEndpoint
from fakts.types import FaktsRequest

logger = logging.getLogger(__name__)


Token = str
EndpointUrl = str


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

    discovery: Discovery
    """The discovery mechanism to use for finding the endpoint"""

    demander: Demander
    """The demander mechanism to use for demanding the token FROM the endpoint"""

    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    """ An ssl context to use for the connection to the endpoint"""

    async def aload(self, request: FaktsRequest):
        """Load the configuration from a remote endpoint"""
        endpoint = await self.discovery.discover(request)
        token = await self.demander.ademand(endpoint, request)

        print(endpoint, token)

        return await self.aclaim(token, endpoint)

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
                    if "status" not in data:
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
