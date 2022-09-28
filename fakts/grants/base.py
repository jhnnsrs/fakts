from pydantic import BaseModel
from fakts.beacon.beacon import FaktsEndpoint
from koil.helpers import unkoil


class GrantException(Exception):
    pass


class FaktsGrant(BaseModel):
    async def aload(self, endpoint: FaktsEndpoint):
        raise NotImplementedError("Fakts need to implement this function")

    def load(self):
        return unkoil(self.aload)
