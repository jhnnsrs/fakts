


from fakts.beacon.beacon import FaktsEndpoint
from fakts.grants.base import FaktsGrant, GrantException
from fakts.beacon import EndpointDiscovery, FaktsRetriever
from rich.prompt import Prompt
from rich.console import Console


class PrompingBeaconGrantException(GrantException):
    pass

class NoBeaconsFound(PrompingBeaconGrantException):
    pass

async def discover_endpoint(name_filter= None):
    discov = EndpointDiscovery()




    return await discov.q(name_filter=name_filter)

async def retrieve_konfik(endpoint: FaktsEndpoint):
    retriev = FaktsRetriever()
    return await retriev.aretrieve(endpoint)


class PromptingBeaconGrant(FaktsGrant):

    def __init__(self, *args, timeout=4, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.timeout = timeout

    async def aload(self, **kwargs):
        discov = EndpointDiscovery()
        console = Console()

        with console.status(f"Waiting {self.timeout} seconds for Beacon Answers"):
            endpoints = await discov.ascan_list(timeout=self.timeout)
        
        if len(endpoints.keys()) == 0: raise NoBeaconsFound("We couldn't find any beacon in your local network")

        choices_name = [key for key, value in endpoints.items()]
        endpoint_name = Prompt.ask("Which Endpoint do you want", choices=choices_name, default=choices_name[0])

        with console.status(f"Please check your broswer window to finish the setup"):
            return await retrieve_konfik(endpoints[endpoint_name])