from socket import socket
from fakts.discovery.base import Discovery
from fakts.discovery.base import FaktsEndpoint
from typing import Dict, Optional

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


async def alisten(bind: ListenBinding, strict: bool = False):

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
                        endpoint = FaktsEndpoint(**endpoint)
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


class AdvertisedDiscovery(Discovery):
    broadcast_port = 45678
    magic_phrase = "beacon-fakts"
    bind = ""
    strict: bool = False
    discovered_endpoints: Dict[str, FaktsEndpoint] = Field(default_factory=dict)
    file = ".fakts.yaml"

    ssl_context: ssl.SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where()),
        exclude=True,
    )
    """ An ssl context to use for the connection to the endpoint"""


    async def check_beacon(self, url: str) -> FaktsEndpoint:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self.ssl_context),
        ) as session:
            async with session.get(
                f"{url}/.well-known/fakts",
            ) as resp:
                data = await resp.json()

                if resp.status == 200:
                    data = await resp.json()
                    if not "name" in data:
                        logger.error(f"Malformed answer: {data}")
                        raise Exception("Malformed Answer")

                    return FaktsEndpoint(**data)

                else:
                    raise Exception("Error! Coud not retrieve on the endpoint")

    async def discover(self, force_refresh=False, **kwargs):
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
            async for i in self.astream():
                endpoint = i
                break

        with open(self.file, "w") as f:
            yaml.dump(cache.dict(), f)

        return endpoint

    async def astream(self, name_filter=None, **kwargs):

        binding = ListenBinding(address=self.bind, port=self.broadcast_port, magic_phrase=self.magic_phrase)
        async for i in alisten(binding, strict=self.strict):
            yield i

       
    def scan(self, **kwargs):
        return unkoil(self.ascan(**kwargs))

    class Config:
        arbitrary_types_allowed = True