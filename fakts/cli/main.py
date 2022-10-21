from typing import List

from rich import get_console
from fakts.beacon.beacon import EndpointBeacon
from fakts.discovery.endpoint import FaktsEndpoint
from rich.prompt import Prompt
import argparse
import netifaces

from fakts.beacon.beacon import Binding


def retrieve_bindings() -> List[Binding]:
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


def main(name=None, url=None):
    if not name:
        name = Prompt.ask(
            "How do you want this beacon to be advertisted as?", default="Arkitekt"
        )

    get_console().print("Which Interface should be used for broadcasting?")
    bindings = retrieve_bindings()
    for i, binding in enumerate(bindings):
        get_console().print(
            f"[{i}] : Use interface {binding.interface}: {binding.bind_addr} advertising to {binding.broadcast_addr}"
        )

    bind_index = Prompt.ask(
        "Which Binding do you want to use?",
        default=1,
        choices=[str(i) for i in range(len(bindings))],
    )

    if not url:
        url = Prompt.ask(
            "Which Setup Uri do you want to advertise?",
            default=f"http://{bindings[int(bind_index)].bind_addr}:8000/f/",
        )

    with EndpointBeacon(
        advertised_endpoints=[FaktsEndpoint(base_url=url, name=name)],
        binding=bindings[int(bind_index)],
    ) as beacon:
        beacon.run()


def entrypoint():
    parser = argparse.ArgumentParser(description="Say hello")
    parser.add_argument("--url", type=str, help="The Name of this script")
    parser.add_argument("--name", type=bool, help="Do you want to refresh")
    args = parser.parse_args()

    main(name=args.name, url=args.url)


if __name__ == "__main__":
    entrypoint()
