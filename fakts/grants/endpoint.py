from pydantic import Field
from fakts.beacon.beacon import FaktsEndpoint
from fakts.grants.base import FaktsGrant
from fakts.beacon import EndpointDiscovery, FaktsRetriever


class EndpointGrant(FaktsGrant):
    endpoint: FaktsEndpoint = Field(default_factory=FaktsEndpoint)
    retriever_protocol: FaktsRetriever = Field(default_factory=FaktsRetriever)

    async def aload(self, previous={}, **kwargs):
        return await self.retriever_protocol.aretrieve(self.endpoint, previous=previous)
