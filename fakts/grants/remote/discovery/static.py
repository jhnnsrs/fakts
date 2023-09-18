from fakts.grants.remote.discovery.base import Discovery
from fakts.grants.remote.discovery.base import FaktsEndpoint


class StaticDiscovery(Discovery):
    base_url = "http://localhost:8000/f/"

    async def discover(self, request):
        return FaktsEndpoint(base_url=self.base_url)

    class Config:
        extra = "forbid"
