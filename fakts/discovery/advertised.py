from socket import socket
from fakts.discovery.base import Discovery
from fakts.discovery.base import Beacon, FaktsEndpoint
from typing import Dict, Optional, AsyncGenerator

from pydantic import Field
from socket import socket, AF_INET, SOCK_DGRAM
import asyncio
import json
from koil import unkoil
import logging
import os
import yaml
import pydantic
from pydantic import BaseModel
import aiohttp
import ssl
import certifi
from .utils import discover_url
from typing import Optional, List

logger = logging.getLogger(__name__)


class DiscoveryProtocol(asyncio.DatagramProtocol):
    pass

    def __init__(self, recvq) -> None:
        super().__init__()
        self._recvq = recvq

    def datagram_received(self, data, addr):
        self._recvq.put_nowait((data, addr))


class AdvertisedConfig(BaseModel):
    selected_endpoint: Optional[FaktsEndpoint]


class ListenBinding(BaseModel):
    address: str = ""
    port: int = 45678
    magic_phrase: str = "beacon-fakts"


async def alisten(bind: ListenBinding, strict: bool = False) -> AsyncGenerator[Beacon, None]:

    s = socket(AF_INET, SOCK_DGRAM)  # create UDP socket
    s.bind((bind.address, bind.port))

    try:

        loop = asyncio.get_event_loop()
        read_queue = asyncio.Queue()
        transport, pr = await loop.create_datagram_endpoint(
            lambda: DiscoveryProtocol(read_queue), sock=s
        )

        while True:
            data, addr = await read_queue.get()
            try:
                data = str(data, "utf8")
                if data.startswith(bind.magic_phrase):
                    endpoint = data[len(bind.magic_phrase) :]

                    try:
                        endpoint = json.loads(endpoint)
                        endpoint = Beacon(**endpoint)
                        yield endpoint

                    except json.JSONDecodeError as e:

                        logger.error("Received Request but it was not valid json")
                        if strict:
                            raise e

                else:
                    logger.error(
                        f"Received Non Magic Response {data}. Maybe somebody sends"
                    )

            except UnicodeEncodeError as e:
                logger.error("Couldn't decode received message")
                if strict:
                    raise e

    except asyncio.CancelledError as e:
        transport.close()
        s.close()
        logger.info("Stopped checking")
        raise e
    finally:
        transport.close()
        s.close()
        logger.info("Stopped checking")


async def alisten_pure(bind: ListenBinding, strict: bool = False) -> AsyncGenerator[Beacon, None]:

    already_detected = set()

    async for x in alisten(bind, strict):
        if x.url not in already_detected:
            already_detected.add(x.url)
            yield x



class AdvertisedDiscovery(Discovery):
    broadcast_port = 45678
    magic_phrase = "beacon-fakts"
    bind = ""
    strict: bool = False
    discovered_endpoints: Dict[str, FaktsEndpoint] = Field(default_factory=dict)
    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    """ An ssl context to use for the connection to the endpoint"""
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

    async def discover(self, force_refresh=False):
        if os.path.exists(self.file):
            with open(self.file, "r") as f:
                x = yaml.load(f, Loader=yaml.FullLoader)
                try:
                    cache = AdvertisedConfig(**x)
                except pydantic.ValidationError as e:
                    logger.error(f"Could not load cache file: {e}. Ignoring it")
                    cache = AdvertisedConfig()
        else:
            cache = AdvertisedConfig()

        if not cache.selected_endpoint or force_refresh:
            binding = ListenBinding(address=self.bind, port=self.broadcast_port, magic_phrase=self.magic_phrase)
            async for beacon in alisten_pure(binding, strict=self.strict):
                try:
                    endpoint = await discover_url(beacon, self.ssl_context)
                    return endpoint
                except Exception as e:
                    logger.error(f"Could not connect to beacon {beacon.url}: {e}")
                    continue



    class Config:
        arbitrary_types_allowed = True