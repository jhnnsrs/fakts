import aiohttp
from typing import Optional
from fakts.grants.remote.base import RemoteGrant, Manifest
from fakts.discovery.base import FaktsEndpoint
from pydantic import Field
import logging

logger = logging.getLogger(__name__)


class RetrieveException(Exception):
    pass


class RetrieveGrant(RemoteGrant):
    """Retrieve Grant

    A retrieve grant is a remote grant can be used to retrieve a token and a configuration from a fakts server, by claiming to be an already
    registed public application on the fakts server. Public applications are applications that are not able to keep a secret, and therefore
    need users to explicitly grant them access to their data. YOu need to also provide a redirect_uri that matches the one that is registered
    on the fakts server.

    """

    manifest: Manifest
    retrieve_url: Optional[str] = Field(
        None,
        description="The url to use for retrieving the token (overwrited the endpoint url)",
    )
    redirect_uri: str

    async def ademand(self, endpoint: FaktsEndpoint) -> str:
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
                    if not "status" in data:
                        raise RetrieveException("Malformed Answer")

                    status = data["status"]
                    if status == "error":
                        raise RetrieveException(data["message"])
                    if status == "granted":
                        return data["token"]

                    raise RetrieveException(f"Unexpected status: {status}")
                else:
                    raise Exception("Error! Coud not claim this app on this endpoint")
