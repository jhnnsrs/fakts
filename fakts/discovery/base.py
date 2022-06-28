from pydantic import BaseModel

from fakts.beacon.beacon import FaktsEndpoint


class Discovery(BaseModel):
    async def discover(self) -> FaktsEndpoint:
        raise NotImplementedError("Discovery needs to implement this function")
