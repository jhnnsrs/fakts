from fakts.handle import TokenLoader
from rath.links.auth import AuthTokenLink
from rath.operation import Operation


class FaktsAuthLink(AuthTokenLink):
    """faktsAuthLink is a link that retrieves a token from oauth2 and sends it to the next link."""

    token_loader: TokenLoader
    """How this link gets and renews its token. Not the whole fakts client:
    authentication is all a link needs once its address is resolved."""

    async def aload_token(self, operation: Operation) -> str:
        """Get a valid token for this operation."""
        return await self.token_loader.aget_token()

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
        header = operation.context.headers.get("Authorization", "")
        stale = header[len("Bearer ") :] if header.startswith("Bearer ") else None
        return await self.token_loader.arefresh_token(stale_token=stale)
