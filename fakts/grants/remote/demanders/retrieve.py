import aiohttp
from typing import Optional
from pydantic import BaseModel, Field
import logging
from fakts.grants.remote.errors import DemandError
from fakts.grants.remote.types import FaktsEndpoint, FaktsRequest
import ssl
import certifi

logger = logging.getLogger(__name__)


class RetrieveError(DemandError):
    """A base class for all retrieve errors"""

    pass


class RetrieveDemander(BaseModel):
    """Retrieve Demander

    A retrieve grant is a remote grant can be used to retrieve a token and a configuration from a fakts server, by claiming to be an already
    registed public application on the fakts server. Public applications are applications that are not able to keep a secret, and therefore
    need users to explicitly grant them access to their data. YOu need to also provide a redirect_uri that matches the one that is registered
    on the fakts server.

    """

    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    """ An ssl context to use for the connection to the endpoint"""

    manifest: BaseModel
    """ The manifest of the application that is requesting the token"""

    retrieve_url: Optional[str] = Field(
        None,
        description="The url to use for retrieving the token (overwrited the endpoint url)",
    )
    """The url to use for retrieving the token (overwrited the endpoint url)"""

    async def ademand(self, endpoint: FaktsEndpoint, request: FaktsRequest) -> str:
        """Demand a token from the endpoint

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to demand the token from
        request : FaktsRequest
            The request to use for the demand

        Returns
        -------
        str
            The token that was retrieved
        """

        retrieve_url = (
            self.retrieve_url
            or endpoint.retrieve_url
            or f"{endpoint.base_url}retrieve/"
        )

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self.ssl_context)
        ) as session:
            logger.debug(f"Requesting token from {retrieve_url}")
            async with session.post(
                retrieve_url,
                json={
                    "manifest": self.manifest.dict(),
                },
            ) as resp:
                data = await resp.json()

                if resp.status == 200:
                    data = await resp.json()
                    if "status" not in data:
                        raise RetrieveError("Malformed Answer")

                    status = data["status"]
                    if status == "error":
                        raise RetrieveError(data["message"])
                    if status == "granted":
                        return data["token"]

                    raise RetrieveError(f"Unexpected status: {status}")
                else:
                    raise RetrieveError(
                        "Error! Coud not claim this app on this endpoint"
                    )

    class Config:
        """Pydantic Config"""

        arbitrary_types_allowed = True
