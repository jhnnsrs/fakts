import aiohttp
from typing import Optional
from pydantic import BaseModel, Field
import logging
from fakts_next.grants.remote.errors import DemandError
from fakts_next.grants.remote.models import FaktsEndpoint, SSLContextModel
from fakts_next.utils import truncate

logger = logging.getLogger(__name__)


class RetrieveError(DemandError):
    """A base class for all retrieve errors"""

    pass


class RetrieveDemander(SSLContextModel):
    """Retrieve Demander

    A retrieve grant is a remote grant can be used to retrieve a token and a configuration from a fakts_next server, by claiming to be an already
    registed public application on the fakts_next server. Public applications are applications that are not able to keep a secret, and therefore
    need users to explicitly grant them access to their data. YOu need to also provide a redirect_uri that matches the one that is registered
    on the fakts_next server.

    """

    manifest: BaseModel
    """ The manifest of the application that is requesting the token"""

    retrieve_url: Optional[str] = Field(
        None,
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

        retrieve_url = self.retrieve_url or endpoint.retrieve_url or f"{endpoint.base_url}retrieve/"

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=self.ssl_context)) as session:
            logger.debug(f"Requesting token from {retrieve_url}")
            async with session.post(
                retrieve_url,
                json={
                    "manifest": self.manifest.model_dump(),
                },
            ) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json()
                    except Exception as e:
                        body = await resp.text()
                        raise RetrieveError(
                            f"Retrieving the token from {retrieve_url} answered with "
                            f"status 200, but the response is not valid JSON: "
                            f"{truncate(body) or '<empty>'}"
                        ) from e

                    if "status" not in data:
                        raise RetrieveError(
                            f"Retrieving the token from {retrieve_url} answered, but "
                            f"the response is missing the 'status' field. "
                            f"Received: {truncate(str(data))}"
                        )

                    status = data["status"]
                    if status == "error":
                        raise RetrieveError(
                            f"The endpoint '{endpoint.name}' at {retrieve_url} reported "
                            f"an error while retrieving the token: "
                            f"{data.get('message', 'no message provided')}. "
                            f"Is the app registered as a public application on this server?"
                        )
                    if status == "granted":
                        return data["token"]

                    raise RetrieveError(
                        f"Retrieving the token from {retrieve_url} answered with "
                        f"unexpected status '{status}' (expected 'granted' or 'error')."
                    )
                else:
                    body = await resp.text()
                    raise RetrieveError(
                        f"Could not retrieve the token from {retrieve_url}: "
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
