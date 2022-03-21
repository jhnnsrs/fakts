from pydantic import Field
from fakts.beacon.beacon import FaktsEndpoint
from fakts.grants.base import FaktsGrant
from fakts.beacon import EndpointDiscovery, FaktsRetriever


async def discover_endpoint(name_filter=None):
    discov = EndpointDiscovery()
    return await discov.ascan_first(name_filter=name_filter)


class BeaconGrant(FaktsGrant):
    discovery_protocol: EndpointDiscovery = Field(default_factory=EndpointDiscovery)
    retriever_protocol: FaktsRetriever = Field(default_factory=FaktsRetriever)
    timeout: int = 4

    async def aload(self, previous={}, **kwargs):
        endpoint = await self.discovery_protocol.ascan_first(**previous)
        return await self.retriever_protocol.aretrieve(endpoint, previous=previous)
