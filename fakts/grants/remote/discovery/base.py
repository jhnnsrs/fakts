from pydantic import BaseModel
from typing import Optional
from fakts.grants.remote.types import FaktsEndpoint
from fakts.types import FaktsRequest


class Beacon(BaseModel):
    url: str


class Discovery(BaseModel):
    """Discovery is the abstract base class for discovery mechanisms

    A discovery mechanism is a way to find a Fakts endpoint
    that can be used to retrieve the configuration.

    This class provides an asynchronous interface, as the discovery can
    envolve lenghty operations such as network requests or waiting for
    user input.
    """

    async def discover(self, request: FaktsRequest) -> FaktsEndpoint:
        raise NotImplementedError("Discovery needs to implement this function")
