


from fakts.beacon.beacon import FaktsEndpoint
from fakts.grants.base import FaktsGrant
from fakts.beacon import EndpointDiscovery, FaktsRetriever



async def discover_endpoint(name_filter= None):
    discov = EndpointDiscovery()
    return await discov.ascan_first(name_filter=name_filter)

async def retrieve_konfik(endpoint: FaktsEndpoint):
    retriev = FaktsRetriever()
    return await retriev.aretrieve(endpoint)


class EndpointGrant(FaktsGrant):

    def __init__(self, endpoint: FaktsEndpoint) -> None:
        self._endpoint = endpoint
        super().__init__()

    async def aload(self, **kwargs):
        return await retrieve_konfik(self._endpoint)