from fakts.discovery.beacon import retrieve_bindings, advertise
from fakts.discovery.base import Beacon
import rich_click as click
import asyncio
from arkitekt.cli.init import Manifest, load_manifest, write_manifest
import subprocess
from rich.console import Console
from rich.prompt import Prompt
from rich.progress import Progress, TextColumn
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
import os
import sys

console = Console()

logo = """
    __      _   _      
  / _|__ _| |_| |_ ___
 |  _/ _` | / /  _(_-/
 |_| \__,_|_\_\\__/__/                     
 """

welcome = "The fakts beacon lets you advertise a fakts endpoint on your local network. This is useful if you want to advertise a fakts endpoint to other devices on your local network."


async def adversite_all(bindings, url, interval=1, iterations=10):
    await asyncio.gather(*[advertise(binding, [Beacon(url=url)], interval=interval, iterations=iterations) for binding in bindings])


def advertise_cli(url: str, all=None, interval=1, iterations=10):
    """Advertises the given endpoint on the interface specified by the user


    Args:
        name (str, optional): The name of the faktsendpoint. Defaults to None (user can specify it)
        url (str, optional): The url of the faktsendpont. Defaults to None (user can specify it)
    """


    




@click.group()
def cli():
    """
    Fakts cli lets you interact with the fakts api
    through the command line.
    
    """
    pass

@cli.command("beacon", short_help="Advertises a fakts endpoint")
@click.argument("url")
@click.option("--all", "-a", help="Advertise on all interfaces", is_flag=True)
@click.option("--iterations", "-i", help="How many iterations (-1 equals indefintetly)", default=-1)
@click.option("--interval", "-i", help="Which second interval between broadcast", default=5)
def beacon(url, all, iterations, interval):
    """ Runs the arkitekt app (using a builder)"""

    md = Panel(logo + welcome, title="Fakts Beacon", title_align="center")
    console.print(md)
    try:
        bindings = retrieve_bindings()
    except ImportError as e:
        error = Panel("""netifaces is required to use the advertised discovery. please install it seperately or install fakts with the 'beacon' extras: pip install "fakts\[beacon]" """
        , title="Fakts Beacon", title_align="center", style="red")
        console.print(
            error
        )
        sys.exit(1)


    
    console.print("Which Interface should be used for broadcasting?")
    
    

    all = all or Prompt.ask("Do you want to use all interfaces?", default="y", choices=["y", "n"]) == "y"  

    console.print(f"Advertising endpoint every {interval} seconds " + "forever" if iterations == -1 else f"{iterations} times")


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

        with console.status("Advertising beacon") as status:
            asyncio.run(advertise(bindings[int(bind_index)], [Beacon(url=url)], interval=interval, iterations=iterations))


    else:
        with console.status("Advertising beacons") as status:
            asyncio.run(adversite_all(bindings, url, interval=interval, iterations=iterations))



if __name__ == "__main__":
    cli()
