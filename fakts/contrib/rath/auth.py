from fakts import Fakts
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
        """Renews the token after an operation was rejected.

        The token that just failed is passed along so that concurrent or
        retried 401s collapse into a single renewal. Without it, each retry
        of a rejected operation would rotate the refresh token again —
        spending credentials to re-solve a problem the first renewal already
        fixed.

        This never prompts: :meth:`Fakts.arefresh_token` is non-interactive
        by contract, so a browser can never open in the middle of a request.
        """
        fakts = self.fakts
        header = operation.context.headers.get("Authorization", "")
        stale = header[len("Bearer ") :] if header.startswith("Bearer ") else None
        return await fakts.arefresh_token(stale_token=stale)
