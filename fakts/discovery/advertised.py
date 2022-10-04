from socket import socket
from fakts.discovery.base import Discovery
from fakts.discovery.endpoint import FaktsEndpoint
from typing import Dict

from pydantic import Field
from socket import socket, AF_INET, SOCK_DGRAM
import asyncio
import json
from koil import unkoil
import logging

logger = logging.getLogger(__name__)


class DiscoveryProtocol(asyncio.DatagramProtocol):
    pass

    def __init__(self, recvq) -> None:
        super().__init__()
        self._recvq = recvq

    def datagram_received(self, data, addr):
        self._recvq.put_nowait((data, addr))


class AdvertisedDiscovery(Discovery):
    broadcast_port = 45678
    magic_phrase = "beacon-fakts"
    bind = ""
    strict: bool = False

    discovered_endpoints: Dict[str, FaktsEndpoint] = Field(default_factory=dict)

    async def discover(self):
        return await self.ascan_first()

    async def ascan_first(self, name_filter=None, **kwargs):

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

    async def ascan_gen(self, name_filter=None, **kwargs):

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

    async def ascan_list(self, timeout=5, **kwargs):
        async def appender():
            async for i in self.ascan_gen(**kwargs):
                logger.debug(f"Disocvered {i} in Time")

        try:
            appending_task = await asyncio.wait_for(
                appender(), timeout=timeout
            )  # async for should cancel this task
        except asyncio.TimeoutError as e:
            logger.info("Stopped checking")
            return self.discovered_endpoints

    def scan(self, **kwargs):
        return unkoil(self.ascan(**kwargs))
