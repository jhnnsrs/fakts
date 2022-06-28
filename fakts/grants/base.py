from pydantic import BaseModel, Field
from fakts.beacon.beacon import FaktsEndpoint
from fakts.discovery.base import Discovery
from fakts.discovery.static import StaticDiscovery
from koil import koil
from koil.helpers import unkoil


class GrantException(Exception):
    pass


class FaktsGrant(BaseModel):
    async def aload(self, endpoint: FaktsEndpoint):
        raise NotImplementedError("Fakts need to implement this function")

    def load(self):
        return unkoil(self.aload)
