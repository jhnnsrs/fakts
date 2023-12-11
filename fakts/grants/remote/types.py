from typing import Protocol, runtime_checkable, Optional, Dict
from pydantic import BaseModel
from fakts.types import FaktsRequest, FaktValue


class FaktsEndpoint(BaseModel):
    """FaktsEndpoint

    A FaktsEndpoint is a remote endpoint that can be used to
    retrieve the configuration. This class is used to represent
    the endpoints that are discovered by the discovery mechanisms.
    (For example, when accessing a well-known fakts URL)"""

    base_url: str = "http://localhost:8000/f/"
    """The base URL of the endpoint. Akin to the base URL of a Oauth2 """
    name: str = "Helper"
    """ A human readable name for the endpoint"""
    description: Optional[str] = None
    """ A human readable description for the endpoint"""
    retrieve_url: Optional[str] = None
    claim_url: Optional[str] = None
    version: Optional[str] = None


@runtime_checkable
class Demander(Protocol):
    """A demander takes a FaktsEndpoint and returns the Fakts
    user input.
    """

    async def ademand(self, endpoint: FaktsEndpoint, request: FaktsRequest) -> str:
        """Demands a token for the given endpoint.

        This method should return the token that can be used to retrieve
        the configuration from the endpoint.

        Args:
            endpoint (FaktsEndpoint): The endpoint to demand the token for.
            request (FaktsRequest): The request that is being processed.

        Returns:
            str: The token that can be used to retrieve the configuration.



        """
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

    async def adiscover(self, request: FaktsRequest) -> FaktsEndpoint:
        """Discovers an endpoint.

        This method should return an endpoint that can be used to retrieve
        the configuration. If no endpoint can be found, it should raise
        a DiscoveryError.

        Parameters
        ----------
        request : FaktsRequest
            The request that is being processed.

        Returns
        -------
        FaktsEndpoint
            The endpoint that can be used to retrieve the configuration.
        """
        ...


@runtime_checkable
class Claimer(Protocol):
    """Discovery is the abstract base class for discovery mechanisms

    A discovery mechanism is a way to find a Fakts endpoint
    that can be used to retrieve the configuration.

    This class provides an asynchronous interface, as the discovery can
    envolve lenghty operations such as network requests or waiting for
    user input.
    """

    async def aclaim(
        self, token: str, endpoint: FaktsEndpoint, request: FaktsRequest
    ) -> Dict[str, FaktValue]:
        """Discovers an endpoint.

        This method should return an endpoint that can be used to retrieve
        the configuration. If no endpoint can be found, it should raise
        a DiscoveryError.

        Parameters
        ----------
        request : FaktsRequest
            The request that is being processed.

        Returns
        -------
        FaktsEndpoint
            The endpoint that can be used to retrieve the configuration.
        """
        ...
