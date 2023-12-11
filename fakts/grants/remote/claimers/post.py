from pydantic import Field
import ssl
import certifi
import aiohttp
from typing import Dict
from fakts.grants.remote.errors import ClaimError
from fakts.grants.remote.types import FaktsEndpoint, FaktsRequest, FaktValue
from pydantic import BaseModel


class ClaimEndpointClaimer(BaseModel):
    """A claimer that claims the configuration from the endpoint

    This claimer is used to claim the configuration from the endpoint.
    This is the default claimer, and it is used by the default
    Remote Grants.


    """

    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    """ An ssl context to use for the connection to the endpoint"""

    async def aclaim(
        self, token: str, endpoint: FaktsEndpoint, request: FaktsRequest
    ) -> Dict[str, FaktValue]:
        """Claims the configuration from the endpoint

        Parameters
        ----------
        token : str
            The token to use to claim the configuration
        endpoint : FaktsEndpoint
            The endpoint to claim the configuration from
        request : FaktsRequest
            The request to use to claim the configuration

        Returns
        -------
        Dict[str, FaktValue]
            The configuration

        Raises
        ------
        ClaimError
            An error occured while claiming the configuration
        """

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
                    raise ClaimError("Error! Coud not claim this app on this endpoint")

    class Config:
        """A pydantic config class"""

        arbitrary_types_allowed = True
