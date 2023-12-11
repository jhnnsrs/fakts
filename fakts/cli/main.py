from fakts.cli.advertise import (
    advertise,
    retrieve_bindings,
    AdvertiseBinding,
    AdvertiseBeacon,
)
import rich_click as click
import asyncio
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
import sys
from typing import List

console = Console()

logo = """
    __      _   _      
  / _|__ _| |_| |_ ___
 |  _/ _` | / /  _(_-/
 |_| \__,_|_\_\\__/__/                     
 """

welcome = "The fakts beacon lets you advertise a fakts endpoint on your local network. This is useful if you want to advertise a fakts endpoint to other devices on your local network."


async def adversite_all(
    bindings: List[AdvertiseBinding],
    beacons: List[AdvertiseBeacon],
    interval: int = 1,
    iterations: int = 10,
) -> None:
    """Advertise on all bindings

    This function will advertise on all bindings
    all beacons.  And will wait for all of them to finish.

    Parameters
    ----------
    bindings : List[AdvertiseBinding]
        The bindings to use
    beacons : List[AdvertiseBeacon]
        The beacons / well-known-endpoints to advertise
    interval : int, optional
        How often to advertise (in seconds), by default 1
    iterations : int, optional
        How often should we adversite? If -1 its infiinite, by default 10
    """

    await asyncio.gather(
        *[
            advertise(binding, beacons, interval=interval, iterations=iterations)
            for binding in bindings
        ]
    )


@click.group()
def cli() -> None:
    """
    Fakts cli lets you interact with the fakts api
    through the command line.

    """
    pass


@cli.command("beacon", short_help="Advertises a fakts endpoint")
@click.argument("url")
@click.option("--all", "-a", help="Advertise on all interfaces", is_flag=True)
@click.option(
    "--iterations",
    "-i",
    help="How many iterations (-1 equals indefintetly)",
    default=-1,
    type=int,
)
@click.option(
    "--interval",
    "-i",
    type=int,
    help="Which second interval between broadcast",
    default=5,
)
def beacon(url: str, all: bool, iterations: int, interval: int) -> None:
    """Runs the arkitekt app (using a builder)"""

    md = Panel(logo + welcome, title="Fakts Beacon", title_align="center")
    console.print(md)
    try:
        bindings = retrieve_bindings()
    except ImportError:
        error = Panel(
            """netifaces is required to use the advertised discovery. please install it seperately or install fakts with the 'beacon' extras: pip install "fakts\[beacon]" """,
            title="Fakts Beacon",
            title_align="center",
            style="red",
        )
        console.print(error)
        sys.exit(1)

    console.print("Which Interface should be used for broadcasting?")

    all = (
        all
        or Prompt.ask(
            "Do you want to use all interfaces?", default="y", choices=["y", "n"]
        )
        == "y"
    )

    console.print(
        f"Advertising endpoint every {interval} seconds " + "forever"
        if iterations == -1
        else f"{iterations} times"
    )

    if not all:
        for i, binding in enumerate(bindings):
            console.print(
                f"[{i}] : Use interface {binding.interface}: {binding.bind_addr} advertising to {binding.broadcast_addr}"
            )

        bind_index = Prompt.ask(
            "Which Binding do you want to use?",
            default=1,
            choices=[str(i) for i in range(len(bindings))],
        )

        with console.status("Advertising beacon"):
            asyncio.run(
                advertise(
                    bindings[int(bind_index)],
                    [AdvertiseBeacon(url=url)],
                    interval=interval,
                    iterations=iterations,
                )
            )

    else:
        with console.status("Advertising beacons"):
            asyncio.run(
                adversite_all(
                    bindings,
                    [AdvertiseBeacon(url=url)],
                    interval=interval,
                    iterations=iterations,
                )
            )


if __name__ == "__main__":
    cli()
