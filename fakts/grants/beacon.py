


from fakts.beacon.beacon import FaktsEndpoint
from fakts.grants.base import FaktsGrant
from fakts.beacon import EndpointDiscovery, FaktsRetriever



async def discover_endpoint(name_filter= None):
    discov = EndpointDiscovery()
    return await discov.ascan(return_on_first_endpoint=True, name_filter=name_filter)

async def retrieve_konfik(endpoint: FaktsEndpoint):
    retriev = FaktsRetriever()
    return await retriev.aretrieve(endpoint)


class BeaconGrant(FaktsGrant):

    async def aload(self, **kwargs):
        endpoint = await discover_endpoint(**kwargs)
        return await retrieve_konfik(endpoint)