"""Provides  a fakts implementaiton of the aiohttp link"""

from typing import Any, Dict, Optional
from pydantic import BaseModel
from fakts_next.fakts import Fakts
from rath.links.aiohttp import AIOHttpLink
from rath.operation import Operation


class AioHttpConfig(BaseModel):
    """AioHttpConfig

    AioHttpConfig is a Fakt that can be used to configure the aiohttp client.
    """

    endpoint_url: str
    """The endpoint url to use for the aiohttp client"""


class FaktsAIOHttpLink(AIOHttpLink):
    """FaktsAIOHttpLink

    A FaktsAIOHttpLink is a link that retrieves the configuration
    from a sorounding fakts context.

    """

    fakts: Fakts
    """The fakts context to use for configuration"""

    fakts_group: str
    """ The fakts group within the fakts context to use for configuration """
    graphql_path: str = "graphql"

    _old_fakt: Optional[Dict[str, Any]] = None

    async def aconfigure(self) -> None:
        """Configure the link with the given fakt"""

        if self.fakts_group == "self":
            alias = await self.fakts.aget_self_alias()
        else:
            alias = await self.fakts.aget_alias(self.fakts_group)

        self.endpoint_url = alias.to_http_path(self.graphql_path)

    async def aconnect(self, operation: Operation) -> None:
        """Connects the link to the server

        This method will retrieve the configuration from the fakts context,
        and configure the link with it. Before connecting, it will check if the
        configuration has changed, and if so, it will reconfigure the link.
        """

        await self.aconfigure()

        return await super().aconnect(operation)
