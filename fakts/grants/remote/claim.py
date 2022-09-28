from typing import Optional
import aiohttp
from fakts.grants.remote.base import RemoteGrant
from fakts.grants.remote.errors import ClaimGrantException


class ClaimGrant(RemoteGrant):
    client_id: str
    client_secret: str
    graph: Optional[str]
    version: Optional[str]

    async def aload(self):

        endpoint = await self.discovery.discover()

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{endpoint.base_url}claim/",
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "graph": self.graph,
                    "version": self.version,
                    "scopes": self.scopes,
                },
            ) as resp:
                data = await resp.json()

                if resp.status == 200:
                    data = await resp.json()
                    if not "status" in data:
                        raise ClaimGrantException("Malformed Answer")

                    status = data["status"]
                    if status == "error":
                        raise ClaimGrantException(data["message"])
                    if status == "granted":
                        return data["config"]

                    raise ClaimGrantException(f"Unexpected status: {status}")
                else:
                    raise Exception("Error! Coud not claim this app on this endpoint")
