import ssl
import certifi
from pydantic import Field, BaseModel
import logging
from typing import List
from .utils import discover_url
from fakts.types import FaktsRequest
from fakts.grants.remote import FaktsEndpoint

logger = logging.getLogger(__name__)


class WellKnownDiscovery(BaseModel):
    """A discovery that uses the well-known endpoint

    A well-known endpoint is a special endpoint that is used to discover
    the actual endpoint. This is useful for example in scenarious where the
    fakts server might change its location, and the client needs to find it,
    easily.

    This discovery mechanism also provides ways to configure the discovery
    process, such as the timeout, the ssl context, and the protocols to try
    if no protocol is specified in the url.

    """

    url: str
    """The url of the well-known endpoint"""
    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    """ An ssl context to use for the connection to the endpoint"""
    allow_appending_slash: bool = Field(
        default=True,
        description="If the url does not end with a slash, should we append one? ",
    )
    """If the url does not end with a slash, should we append one? A well-known endpoint should end with a slash"""
    auto_protocols: List[str] = Field(
        default_factory=lambda: [],
        description="If no protocol is specified, we will try to connect to the following protocols",
    )
    """ If no protocol is specified, we will try to connect to the following protocols"""
    timeout: int = Field(
        default=3,
        description="The timeout for the connection",
    )
    """A timeout for the connection to the well-known endpoint. Applies to each protocol"""

    async def adiscover(self, request: FaktsRequest) -> FaktsEndpoint:
        """Discover the endpoint

        This method will try to discover the endpoint using the well-known
        endpoint. It will try to connect to the well-known endpoint using
        the protocols specified in the configuration, and the timeout
        specified in the configuration.

        Parameters
        ----------
        request : FaktsRequest
            The request to use for the discovery process (is not used)

        Returns
        -------
        FaktsEndpoint
            A valid endpoint
        """

        return await discover_url(
            self.url,
            self.ssl_context,
            auto_protocols=self.auto_protocols,
            allow_appending_slash=self.allow_appending_slash,
            timeout=self.timeout,
        )

    class Config:
        """Pydantic Config"""

        extra = "forbid"
        arbitrary_types_allowed = True
