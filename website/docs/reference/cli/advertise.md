---
sidebar_label: advertise
title: cli.advertise
---

## BeaconProtocol Objects

```python
class BeaconProtocol(asyncio.DatagramProtocol)
```

A protocol that sends beacons to a broadcast address

This protocol is used to send beacons to a broadcast address.
It is used by the advertise function.

## AdvertiseBeacon Objects

```python
class AdvertiseBeacon(BaseModel)
```

A beacon that is sent when advertising

## AdvertiseBinding Objects

```python
class AdvertiseBinding(BaseModel)
```

A binding for the advertise function

This binding specifies the interface to use, the broadcast address
and the address to bind to. It also specifies the port to use and
a magic phrase that is used to identify the beacon.

It is retrieved by the retrieve_bindings function, and
used by the advertise function.

#### retrieve\_bindings

```python
def retrieve_bindings() -> List[AdvertiseBinding]
```

Uses the netifaces library to retrieve all available interfaces and
if they are up and running and have a broadcast address, it will return
a list of bindings for the beacon to use.

**Raises**:

- `ImportError` - An importError is raised if the netifaces library is not installed
  

**Returns**:

- `List[Binding]` - The list of bindings

#### advertise

```python
async def advertise(binding: AdvertiseBinding,
                    endpoints: List[AdvertiseBeacon],
                    interval: int = 1,
                    iterations: int = 10) -> None
```

Advertises the given endpoints on the given binding

This function opens a udp socket and sends the endpoints as json to the broadcast address
on the given port. It will repeat this for the given number of iterations with the given
interval in between.

If interval is -1 it will repeat forever, until this task is cancelled

**Arguments**:

- `binding` _Binding_ - The binding to use (interface, broadcast address, port)
- `endpoints` _List[FaktsEndpoint]_ - The list of endpoints to advertise
- `interval` _int, optional_ - The interval between a beacon send in seconds. Defaults to 1.
- `iterations` _int, optional_ - The amount of sends that should happen, -1 means infinite (until cancelled). Defaults to 10.

