---
sidebar_label: static
title: grants.remote.discovery.static
---

## StaticDiscovery Objects

```python
class StaticDiscovery(BaseModel)
```

A discovery that always returns the same endpoint

This is mostly used for testing purposes.

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

