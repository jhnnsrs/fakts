from fakts.discovery.base import Discovery
from fakts.discovery.base import FaktsEndpoint
from fakts.discovery.errors import DiscoveryError
import ssl
import certifi
from pydantic import Field
import aiohttp
import logging
from typing import List
import asyncio
from .utils import discover_url

logger = logging.getLogger(__name__)


class WellKnownDiscovery(Discovery):
    url = "http://localhost:8000"
    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    allow_appending_slash: bool = Field(
        default=True,
        description="If the url does not end with a slash, should we append one? ",
    )
    auto_protocols: List[str] = Field(
        default_factory=lambda: [],
        description="If no protocol is specified, we will try to connect to the following protocols",
    )
    timeout: int = Field(
        default=3,
        description="The timeout for the connection",
    )

    async def discover(self):
        return await discover_url(self.url, self.ssl_context, auto_protocols=self.auto_protocols, allow_appending_slash=self.allow_appending_slash, timeout=self.timeout)

    class Config:
        extra = "forbid"
        arbitrary_types_allowed = True
