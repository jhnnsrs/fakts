---
sidebar_label: cache
title: grants.remote.discovery.cache
---

## AutoSaveCacheStore Objects

```python
class AutoSaveCacheStore(BaseModel)
```

An implementation of EndpointStore that stores the endpoint in a file

This is a simple implementation that stores the endpoint in a file.
And will be used if no other implementation is found.

#### aput\_default\_endpoint

```python
async def aput_default_endpoint(endpoint: Optional[FaktsEndpoint]) -> None
```

Puts the default endpoint

Stores the endpoint in the cache file

Parameters
----------
endpoint : Optional[FaktsEndpoint]
    The (stored) default endpoint

#### aget\_default\_endpoint

```python
async def aget_default_endpoint() -> Optional[FaktsEndpoint]
```

Gets the default endpoint

Gets the endpoint from the cache file

Returns
-------
Optional[FaktsEndpoint]
    The (stored) default endpoint

## Config Objects

```python
class Config()
```

Pydantic config

