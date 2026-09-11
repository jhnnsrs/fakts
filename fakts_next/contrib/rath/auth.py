from fakts_next import Fakts
from rath.links.auth import AuthTokenLink
from rath.operation import Operation


class FaktsAuthLink(AuthTokenLink):
    """faktsAuthLink is a link that retrieves a token from oauth2 and sends it to the next link."""

    fakts: Fakts

    async def aload_token(self, operation: Operation) -> str:
        """Retrieves the token from herre"""
        fakts = self.fakts
        return await fakts.aget_token()

    async def arefresh_token(self, operation: Operation) -> str:
        """Refreshes the token from herre"""
        fakts = self.fakts
        return await fakts.arefresh_token()
