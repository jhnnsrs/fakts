import aiohttp
from fakts_next.grants.remote.errors import ClaimError
from fakts_next.grants.remote.models import FaktsEndpoint, SSLContextModel

from fakts_next.models import ActiveFakts
from fakts_next.utils import truncate


class ClaimEndpointClaimer(SSLContextModel):
    """A claimer that claims the configuration from the endpoint

    This claimer is used to claim the configuration from the endpoint.
    This is the default claimer, and it is used by the default
    Remote Grants.


    """

    async def aclaim(
        self,
        token: str,
        endpoint: FaktsEndpoint,
    ) -> ActiveFakts:
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

        claim_url = f"{endpoint.base_url}claim/"

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self.ssl_context)
        ) as session:
            async with session.post(
                claim_url,
                json={
                    "token": token,
                    "secure": endpoint.base_url.startswith("https"),
                },
            ) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json()
                    except Exception as e:
                        body = await resp.text()
                        raise ClaimError(
                            f"Claiming the configuration from {claim_url} answered "
                            f"with status 200, but the response is not valid JSON: "
                            f"{truncate(body) or '<empty>'}"
                        ) from e

                    if "status" not in data:
                        raise ClaimError(
                            f"Claiming the configuration from {claim_url} answered, "
                            f"but the response is missing the 'status' field. "
                            f"Received: {truncate(str(data))}"
                        )

                    status = data["status"]
                    if status == "error":
                        raise ClaimError(
                            f"The endpoint '{endpoint.name}' at {claim_url} reported "
                            f"an error while claiming the configuration: "
                            f"{data.get('message', 'no message provided')}"
                        )
                    if status == "granted":
                        fakts = ActiveFakts(**data["config"])
                        return fakts
                    if status == "denied":
                        raise ClaimError(
                            f"The endpoint '{endpoint.name}' at {claim_url} denied the "
                            f"claim. The claim token may be expired or revoked — "
                            f"re-registering the app (e.g. by resetting the cache) "
                            f"should issue a new one."
                        )

                    raise ClaimError(
                        f"Claiming the configuration from {claim_url} answered with "
                        f"unexpected status '{status}' "
                        f"(expected 'granted', 'denied' or 'error')."
                    )
                else:
                    body = await resp.text()
                    raise ClaimError(
                        f"Could not claim the configuration from {claim_url}: "
                        f"status code {resp.status}. "
                        f"Response body: {truncate(body) or '<empty>'}"
                    )
