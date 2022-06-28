from typing import List, Optional
from pydantic import BaseModel
from socket import socket, AF_INET, SOCK_DGRAM, SOL_SOCKET, SO_BROADCAST, getaddrinfo
import asyncio
import json
from fakts.discovery.endpoint import FaktsEndpoint
from koil import unkoil, koilable, Koil
from koil.composition import KoiledModel
import logging


logger = logging.getLogger(__name__)


class BeaconProtocol(asyncio.DatagramProtocol):
    pass


class Binding(BaseModel):
    interface: str
    broadcast_addr: str
    bind_addr: str
    broadcast_port: int = 45678
    magic_phrase: str = "beacon-fakts"


class EndpointBeacon(KoiledModel):
    koil: Optional[Koil]
    advertised_endpoints: List[FaktsEndpoint]
    binding: Binding
    interval: int = 5

    def endpoint_to_message(self, config: FaktsEndpoint):
        return bytes(self.binding.magic_phrase + json.dumps(config.dict()), "utf8")

    async def arun(self):
        s = socket(AF_INET, SOCK_DGRAM)  # create UDP socket.
        s.bind((self.binding.bind_addr, 0))
        s.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)  # this is a broadcast socket

        loop = asyncio.get_event_loop()
        transport, pr = await loop.create_datagram_endpoint(BeaconProtocol, sock=s)

        messages = [
            self.endpoint_to_message(config) for config in self.advertised_endpoints
        ]

        while True:
            for message in messages:
                transport.sendto(
                    message, (self.binding.broadcast_addr, self.binding.broadcast_port)
                )
                logger.info(f"Send Message {message}")

            await asyncio.sleep(self.interval)

    def run(self):
        return unkoil(self.arun)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
