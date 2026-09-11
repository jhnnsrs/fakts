from fakts_next.fakts import Fakts
from rath.links.httpx import HttpxLink
from rath.operation import Operation


class FaktsHttpXLink(HttpxLink):
    """FaktsHttpXLink


    A FaktsHttpXLink is a HttpxLink that retrieves the configuration
    from a passed fakts context.

    """

    fakts: Fakts
    """ The fakts context to use for configuration"""

    fakts_group: str
    """The service key within the fakts context to resolve the endpoint for"""
    graphql_path: str = "graphql"

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
