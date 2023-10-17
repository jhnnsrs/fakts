from typing import Protocol, runtime_checkable, Optional
from pydantic import BaseModel
from fakts.types import FaktsRequest

Token = str


class FaktsEndpoint(BaseModel):
    base_url = "http://localhost:8000/f/"
    name: str = "Helper"
    description: Optional[str]
    retrieve_url: Optional[str]
    claim_url: Optional[str]
    version: Optional[str]


@runtime_checkable
class Demander(Protocol):
    """A demander takes a FaktsEndpoint and returns the Fakts
    user input.
    """

    async def ademand(self, endpoint: FaktsEndpoint, request: FaktsRequest) -> Token:
        ...


@runtime_checkable
class Discovery(Protocol):
    """Discovery is the abstract base class for discovery mechanisms

    A discovery mechanism is a way to find a Fakts endpoint
    that can be used to retrieve the configuration.

    This class provides an asynchronous interface, as the discovery can
    envolve lenghty operations such as network requests or waiting for
    user input.
    """

    async def discover(self, request: FaktsRequest) -> FaktsEndpoint:
        ...
