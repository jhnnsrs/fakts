from typing import List, Optional
from pydantic import BaseModel
from socket import AF_INET, SOCK_DGRAM, SOL_SOCKET, SO_BROADCAST, socket
import asyncio
import json
from fakts.discovery.base import FaktsEndpoint, Beacon
from koil import Koil, unkoil
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


def retrieve_bindings() -> List[Binding]:
    """Uses the netifaces library to retrieve all available interfaces and
    if they are up and running and have a broadcast address, it will return
    a list of bindings for the beacon to use.

    Raises:
        ImportError: An importError is raised if the netifaces library is not installed

    Returns:
        List[Binding]: The list of bindings
    """

    try:
        import netifaces
    except ImportError as e:
        raise ImportError(
            "netifaces is required to use the advertised discovery. please install it seperately or install fakts with the 'beacon' extras"
        ) from e

    potential_bindings: List[Binding] = []

    for interface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addrs:
            informations = addrs[netifaces.AF_INET]
            for i in informations:

                if "broadcast" in i:
                    potential_bindings.append(
                        Binding(
                            interface=interface,
                            bind_addr=i["addr"],
                            broadcast_addr=i["broadcast"],
                        )
                    )
    return potential_bindings


async def advertise(
    binding: Binding,
    endpoints: List[Beacon],
    interval: int = 1,
    iterations: int = 10,
) -> None:
    """Advertises the given endpoints on the given binding

    This function opens a udp socket and sends the endpoints as json to the broadcast address
    on the given port. It will repeat this for the given number of iterations with the given
    interval in between.

    If interval is -1 it will repeat forever, until this task is cancelled

    Args:
        binding (Binding): The binding to use (interface, broadcast address, port)
        endpoints (List[FaktsEndpoint]): The list of endpoints to advertise
        interval (int, optional): The interval between a beacon send in seconds. Defaults to 1.
        iterations (int, optional): The amount of sends that should happen, -1 means infinite (until cancelled). Defaults to 10.

    """

    s = socket(AF_INET, SOCK_DGRAM)  # create UDP socket.

    try:
        s.bind((binding.bind_addr, 0))
        s.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)  # this is a broadcast socket

        loop = asyncio.get_event_loop()
        transport, pr = await loop.create_datagram_endpoint(BeaconProtocol, sock=s)

        messages = [
            bytes(binding.magic_phrase + json.dumps(beacon.dict()), "utf8")
            for beacon in endpoints
        ]
        i = 1
        while i <= iterations or iterations == -1:
            for message in messages:
                transport.sendto(
                    message, (binding.broadcast_addr, binding.broadcast_port)
                )
                logger.debug(f"Send Message {message}")

            await asyncio.sleep(interval)
            i += 1
    except asyncio.CancelledError as e:
        transport.close()
        s.close()
        raise e

