"""What a service is handed instead of the whole configuration client.

A service needs two things from fakts, and only two: the **address** of each
service it requires, and a way to get an **access token**. The first is an
:class:`~fakts.models.Alias`, resolved once when the run connects; the second is
a :class:`TokenLoader`.

Neither is the fakts client. That is the point: a builder written against these
is a pure function of resolved configuration, so it can be built from a literal
address and a two-line token stub, with no configuration system in sight.

An alias is resolved once per run and does not change under a live client. An
alias is a route to *one specific service*, and changing which service a client
talks to mid-execution is not supported -- if a deployment moves, the run ends
and a new one resolves afresh. A token, by contrast, must stay live: it expires,
and rotating it is what :class:`TokenLoader` is for.
"""

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class TokenLoader(Protocol):
    """A way to get, and renew, an access token.

    The two operations :class:`~fakts.contrib.rath.auth.FaktsAuthLink` needs --
    which is all any service needs of fakts once its addresses are resolved.
    :class:`~fakts.Fakts` satisfies this structurally, so nothing has to adapt it.
    """

    async def aget_token(self) -> str:
        """Get a valid access token, fetching or renewing one if needed.

        Returns:
            The token, without a ``Bearer`` prefix.
        """
        ...

    async def arefresh_token(self, stale_token: Optional[str] = None) -> str:
        """Renew the access token after one was rejected.

        Args:
            stale_token: The token that was just refused, when it is known.
                Concurrent and retried 401s that pass the same stale token
                collapse into a single renewal -- without it, each retry rotates
                the refresh token again, spending credentials to re-solve a
                problem the first renewal already fixed.

        Returns:
            The renewed token.
        """
        ...


__all__ = ["TokenLoader"]
