from rich import get_console
from fakts.discovery.beacon import retrieve_bindings, EndpointBeacon
from fakts.discovery.base import FaktsEndpoint
from rich.prompt import Prompt
import argparse


def main(name: str = None, url: str = None):
    """Advertises the given endpoint on the interface specified by the user


    Args:
        name (str, optional): The name of the faktsendpoint. Defaults to None (user can specify it)
        url (str, optional): The url of the faktsendpont. Defaults to None (user can specify it)
    """

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
