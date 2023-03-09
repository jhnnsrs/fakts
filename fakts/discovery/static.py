from fakts.discovery.base import Discovery
from fakts.discovery.base import FaktsEndpoint


class StaticDiscovery(Discovery):
    base_url = "http://localhost:8000/f/"

    async def discover(self):

        


        return FaktsEndpoint(base_url=self.base_url)

    class Config:
        extra = "forbid"
