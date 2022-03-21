from pydantic import Field
from fakts.beacon.beacon import FaktsEndpoint
from fakts.grants.base import FaktsGrant, GrantException
from fakts.beacon import EndpointDiscovery, FaktsRetriever

try:
    from rich.prompt import Prompt
    from rich.console import Console
except ImportError as e:

    raise ImportError(
        "To use the cli, you need to install rich. Ex `pip install rich`"
    ) from e


class PrompingBeaconGrantException(GrantException):
    pass


class NoBeaconsFound(PrompingBeaconGrantException):
    pass


class CLIBeaconGrant(FaktsGrant):
    discovery_protocol: EndpointDiscovery = Field(default_facotry=EndpointDiscovery)
    retriever_protocol: FaktsRetriever = Field(default_facotry=FaktsRetriever)
    timeout: int = 4

    async def aload(self, previous={}, **kwargs):

        console = Console()
        with console.status(f"Waiting {self._timeout} seconds for Beacon Answers"):
            endpoints = await self.discovery_protocol.ascan_list(timeout=self.timeout)

        if len(endpoints.keys()) == 0:
            raise NoBeaconsFound("We couldn't find any beacon in your local network")

        choices_name = [key for key, value in endpoints.items()]
        endpoint_name = Prompt.ask(
            "Which Endpoint do you want", choices=choices_name, default=choices_name[0]
        )

        with console.status(f"Please check your browser window to finish the setup"):
            return await self.retriever_protocol.aretrieve(
                endpoints[endpoint_name], previous
            )
