import ssl
from typing import Protocol, runtime_checkable, Optional

import certifi
from pydantic import BaseModel, ConfigDict, Field
from fakts_next.models import ActiveFakts


class SSLContextModel(BaseModel):
    """Base model that carries an SSL context and allows arbitrary types.

    Shared by the remote grant components (discovery, demanders, claimers)
    that need to make TLS connections to a fakts_next server.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    """An ssl context to use for the connection to the endpoint."""


class FaktsEndpoint(BaseModel):
    """FaktsEndpoint

    A FaktsEndpoint is a remote endpoint that can be used to
    retrieve the configuration. This class is used to represent
    the endpoints that are discovered by the discovery mechanisms.
    (For example, when accessing a well-known fakts_next URL)"""

    base_url: str = "http://localhost:8000/f/"
    """The base URL of the endpoint. Akin to the base URL of a Oauth2 """
    name: str = "Helper"
    """ A human readable name for the endpoint"""
    description: Optional[str] = None
    """ A human readable description for the endpoint"""
    retrieve_url: Optional[str] = None
    claim_url: Optional[str] = None
    configure_url: Optional[str] = None
    """The user-facing page where a device code can be entered/approved.
    If the server does not advertise it, clients fall back to deriving it
    from the base_url."""
    version: Optional[str] = None
    """The version of the server software (informational)"""
    protocol_version: Optional[str] = None
    """The version of the fakts protocol the server speaks. Servers that
    do not advertise it are treated as speaking protocol version "1"."""


@runtime_checkable
class Demander(Protocol):
    """A demander takes a FaktsEndpoint and returns the Fakts
    user input.
    """

    async def ademand(self, endpoint: FaktsEndpoint) -> str:
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

    async def adiscover(self) -> FaktsEndpoint:
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
    """Claimer is the abstract base class for claiming mechanisms

    A claimer uses a token to claim (retrieve) the active configuration
    from a previously discovered Fakts endpoint.

    This class provides an asynchronous interface, as claiming can
    involve lengthy operations such as network requests.
    """

    async def aclaim(self, token: str, endpoint: FaktsEndpoint) -> ActiveFakts:
        """Claims the configuration from the endpoint.

        This method should use the token to retrieve the active configuration
        from the endpoint. If the configuration cannot be claimed, it should
        raise a ClaimError.

        Parameters
        ----------
        token : str
            The token to use for claiming the configuration.
        endpoint : FaktsEndpoint
            The endpoint to claim the configuration from.

        Returns
        -------
        ActiveFakts
            The active configuration claimed from the endpoint.
        """
        ...
