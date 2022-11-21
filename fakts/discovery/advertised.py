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
            endpoint = await self.aget()

        with open(self.file, "w") as f:
            yaml.dump(cache.dict(), f)

        return await self.aget()

    async def aget(self, name_filter=None, **kwargs):

        s = socket(AF_INET, SOCK_DGRAM)  # create UDP socket
        s.bind((self.bind, self.broadcast_port))

        loop = asyncio.get_event_loop()
        read_queue = asyncio.Queue()
        transport, pr = await loop.create_datagram_endpoint(
            lambda: DiscoveryProtocol(read_queue), sock=s
        )

        while True:
            data, addr = await read_queue.get()
            try:
                data = str(data, "utf8")
                if data.startswith(self.magic_phrase):
                    endpoint = data[len(self.magic_phrase) :]

                    try:
                        endpoint = json.loads(endpoint)
                        endpoint = FaktsEndpoint(**endpoint)
                        if name_filter and endpoint.name != name_filter:
                            continue
                        transport.close()
                        return endpoint

                    except json.JSONDecodeError as e:
                        logger.error("Received Request but it was not valid json")
                        if self.strict:
                            raise e

                    except Exception as e:
                        logger.error(f"Received Request caused Exception {e}")
                        if self.strict:
                            raise e
                else:
                    logger.error(
                        f"Received Non Magic Response {data}. Maybe somebody sends"
                    )

            except UnicodeEncodeError as e:
                logger.info("Couldn't decode received message")
                if self.strict:
                    raise e

    async def astream(self, name_filter=None, **kwargs):

        s = socket(AF_INET, SOCK_DGRAM)  # create UDP socket
        s.bind((self.bind, self.broadcast_port))

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
                    if data.startswith(self.magic_phrase):
                        endpoint = data[len(self.magic_phrase) :]

                        try:
                            endpoint = json.loads(endpoint)
                            endpoint = FaktsEndpoint(**endpoint)
                            if name_filter and endpoint.name != name_filter:
                                continue
                            if endpoint.name not in self.discovered_endpoints:
                                yield endpoint
                                self.discovered_endpoints[endpoint.name] = endpoint

                        except json.JSONDecodeError as e:
                            logger.error("Received Request but it was not valid json")
                            if self.strict:
                                raise e

                        except Exception as e:
                            logger.error(f"Received Request caused Exception {e}")
                            if self.strict:
                                raise e
                    else:
                        logger.error(
                            f"Received Non Magic Response {data}. Maybe somebody sends"
                        )

                except UnicodeEncodeError as e:
                    logger.error("Couldn't decode received message")
                    if self.strict:
                        raise e

        except asyncio.CancelledError as e:
            s.close()
            logger.info("Stopped checking")
            raise e

    def scan(self, **kwargs):
        return unkoil(self.ascan(**kwargs))
