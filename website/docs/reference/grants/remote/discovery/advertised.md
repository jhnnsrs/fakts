---
sidebar_label: advertised
title: grants.remote.discovery.advertised
---

## DiscoveryProtocol Objects

```python
class DiscoveryProtocol(asyncio.DatagramProtocol)
```

The protocol that is used to receive beacons, and put them in a queue

#### \_\_init\_\_

```python
def __init__(recvq: asyncio.Queue) -> None
```

Initialize the protocol

Parameters
----------
recvq : asyncio.Queue
    The queue to put the beacons in

#### datagram\_received

```python
def datagram_received(data: bytes, addr: Tuple[str, int]) -> None
```

Receive a datagram

This method is called when a datagram is received, and
puts it in the queue

Parameters
----------
data : bytes
    The data that was received
addr : Tuple[str, int]
    The address it was received from

## ListenBinding Objects

```python
class ListenBinding(BaseModel)
```

A binding to listen on for beacons

## Beacon Objects

```python
class Beacon(BaseModel)
```

A beacon that is received when listening on
a broadcast port

#### url

The url of the endpoint

#### alisten

```python
async def alisten(bind: ListenBinding,
                  strict: bool = False) -> AsyncGenerator[Beacon, None]
```

A generator that listens on a broadcast port for beacons

This generator listens on a specific binding for beacons.
It will yield the beacons as it receives.


Parameters
----------
bind : ListenBinding
    The binding to listen on
strict : bool, optional
    Should we error on bad Beacons, by default False


Yields
------
Beacon
    The beacon that was received

Raises
------
e
    Any exception that is raised by the socket

#### alisten\_pure

```python
async def alisten_pure(bind: ListenBinding,
                       strict: bool = False) -> AsyncGenerator[Beacon, None]
```

A generator that listens on a broadcast port for beacons

This generator listens on a specific binding for beacons.
It will yield the beacons as it receives, but will only yield
each beacon once.


Parameters
----------
bind : ListenBinding
    The binding to listen on
strict : bool, optional
    Should we error on bad Beacons, by default False


Yields
------
Beacon
    The beacon that was received

Raises
------
e
    Any exception that is raised by the socket

## FirstAdvertisedDiscovery Objects

```python
class FirstAdvertisedDiscovery(BaseModel)
```

A discovery that will return the first endpoint that is advertised

This discovery will listen on a broadcast port for beacons.
It will then try to connect to the endpoint and return it.

#### broadcast\_port

The port the broadcast on

#### bind

The address to bind to

#### strict

Should we error on bad Beacons

#### discovered\_endpoints

A cache of discovered endpoints

#### ssl\_context

An ssl context to use for the connection to the endpoint

#### adiscover

```python
async def adiscover(request: FaktsRequest) -> FaktsEndpoint
```

Discover the endpoint

This method will always return the same endpoint (the one that was
passed to the constructor)

Parameters
----------
request : FaktsRequest
    The request to use for the discovery process (is not used)

Returns
-------
FaktsEndpoint
    A valid endpoint

## Config Objects

```python
class Config()
```

Pydantic Config

