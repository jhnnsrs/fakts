import aiohttp
from fakts.grants.remote.base import RemoteGrant
from fakts.discovery.base import FaktsEndpoint


class RetrieveException(Exception):
    pass


class RetrieveGrant(RemoteGrant):
    """Retrieve Grant

    A retrieve grant is a remote grant can be used to retrieve a token and a configuration from a fakts server, by claiming to be an already
    registed public application on the fakts server. Public applications are applications that are not able to keep a secret, and therefore
    need users to explicitly grant them access to their data. YOu need to also provide a redirect_uri that matches the one that is registered
    on the fakts server.

    """

    redirect_uri: str

    async def ademand(self, endpoint: FaktsEndpoint) -> str:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self.ssl_context)
        ) as session:
            async with session.post(
                f"{endpoint.base_url}retrieve/",
                json={
                    "version": self.version,
                    "identifier": self.identifier,
                    "redirect_uri": self.redirect_uri,
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
