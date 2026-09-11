import aiohttp
from typing import Optional
from pydantic import BaseModel, Field
import logging
from fakts_next.grants.remote.models import FaktsEndpoint, SSLContextModel
from fakts_next.grants.remote.demanders.retrieve import RetrieveError
from fakts_next.utils import truncate

logger = logging.getLogger(__name__)


class RedeemDemander(SSLContextModel):
    """Redeem Demander

    A reedem grant is a remote grant that can be used to in one shot, create a new client and retrieve a token and a configuration from a fakts_next server.
    The redeem token is a token that was issued by the fakts_next server before, and that can be used to create a any new client (restricted to development
    clients bound to one user). This is useful for creating new clients in an environment where the client CAN keep a secret, but where the clients manifest
    is not known to the fakts_next server.

    """

    manifest: BaseModel
    """ The manifest of the application that is requesting the token"""

    token: str
    """ The token with which to redeem the client"""

    retrieve_url: Optional[str] = Field(
        default=None,
        description="The url to use for retrieving the token (overwrited the endpoint url)",
    )
    """The url to use for retrieving the token (overwrited the endpoint url)"""

    async def ademand(self, endpoint: FaktsEndpoint) -> str:
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

        retrieve_url = self.retrieve_url or endpoint.retrieve_url or f"{endpoint.base_url}redeem/"

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self.ssl_context)
        ) as session:
            logger.debug(f"Requesting token from {retrieve_url}")
            async with session.post(
                retrieve_url,
                json={
                    "manifest": self.manifest.model_dump(),
                    "token": self.token,
                },
            ) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json()
                    except Exception as e:
                        body = await resp.text()
                        raise RetrieveError(
                            f"Redeeming the token at {retrieve_url} answered with "
                            f"status 200, but the response is not valid JSON: "
                            f"{truncate(body) or '<empty>'}"
                        ) from e

                    if "status" not in data:
                        raise RetrieveError(
                            f"Redeeming the token at {retrieve_url} answered, but the "
                            f"response is missing the 'status' field. "
                            f"Received: {truncate(str(data))}"
                        )

                    status = data["status"]
                    if status == "error":
                        raise RetrieveError(
                            f"The endpoint '{endpoint.name}' at {retrieve_url} reported "
                            f"an error while redeeming the token: "
                            f"{data.get('message', 'no message provided')} "
                            f"(redeem tokens are single-use and may have expired)"
                        )
                    if status == "granted":
                        return data["token"]

                    raise RetrieveError(
                        f"Redeeming the token at {retrieve_url} answered with "
                        f"unexpected status '{status}' (expected 'granted' or 'error')."
                    )
                else:
                    body = await resp.text()
                    raise RetrieveError(
                        f"Could not redeem the token at {retrieve_url}: "
                        f"status code {resp.status}. "
                        f"Response body: {truncate(body) or '<empty>'}"
                    )

    async def arefresh(self, endpoint: FaktsEndpoint) -> str:
        """Refreshes the token for the given endpoint.

        This method will refresh the token for the given endpoint. This method will
        request a new code from the fakts_next server. This code will be used to
        authenticate the user. The user will be prompted to visit a URL and enter the code.

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to fetch the token for
        request : FaktsRequest
            The request to use for the fetching of the token

        Returns
        -------
        str
            The token that was refreshed
        """

        return await self.ademand(endpoint)
