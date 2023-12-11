---
sidebar_label: main
title: cli.main
---

#### adversite\_all

```python
async def adversite_all(bindings: List[AdvertiseBinding],
                        beacons: List[AdvertiseBeacon],
                        interval: int = 1,
                        iterations: int = 10) -> None
```

Advertise on all bindings

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

#### cli

```python
@click.group()
def cli() -> None
```

Fakts cli lets you interact with the fakts api
through the command line.

#### beacon

```python
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
def beacon(url: str, all: bool, iterations: int, interval: int) -> None
```

Runs the arkitekt app (using a builder)

