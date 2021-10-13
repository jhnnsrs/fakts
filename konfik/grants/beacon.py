


from konfik.beacon.beacon import KonfikEndpoint
from konfik.grants.base import KonfigGrant
from konfik.beacon import EndpointDiscovery, KonfikRetriever



async def discover_endpoint(name_filter= None):
    discov = EndpointDiscovery()
    return await discov.ascan(return_on_first_endpoint=True, name_filter=name_filter)

async def retrieve_konfik(endpoint: KonfikEndpoint):
    retriev = KonfikRetriever()
    return await retriev.aretrieve(endpoint)


class BeaconGrant(KonfigGrant):

    async def aload(self, **kwargs):
        endpoint = await discover_endpoint(**kwargs)
        return await retrieve_konfik(endpoint)