from pydantic import BaseModel


class FaktsEndpoint(BaseModel):
    base_url = "http://localhost:8000/f/"
    name: str = "Helper"


class Discovery(BaseModel):
    """Discovery is the abstract base class for discovery mechanisms

    A discovery mechanism is a way to find a Fakts endpoint
    that can be used to retrieve the configuration.

    This class provides an asynchronous interface, as the discovery can
    envolve lenghty operations such as network requests or waiting for
    user input.
    """

    async def discover(self, force_refresh=False) -> FaktsEndpoint:
        raise NotImplementedError("Discovery needs to implement this function")
