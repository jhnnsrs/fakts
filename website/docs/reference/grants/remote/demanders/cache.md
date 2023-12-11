---
sidebar_label: cache
title: grants.remote.demanders.cache
---

## EndpointDefaults Objects

```python
class EndpointDefaults(BaseModel)
```

A serialization helper for the
default token store

## CacheTokenStore Objects

```python
class CacheTokenStore(BaseModel)
```

A Cache Token Store

This token store is used to store tokens in a cache file.
It is used by the AutoSaveDemander to cache tokens.

#### aput\_default\_token\_for\_endpoint

```python
async def aput_default_token_for_endpoint(endpoint: FaktsEndpoint,
                                          token: Optional[str]) -> None
```

A function that puts the default token for an endpoint



Parameters
----------
endpoint : FaktsEndpoint
    _description_
token : str
    _description_

#### aget\_default\_token\_for\_endpoint

```python
async def aget_default_token_for_endpoint(
        endpoint: FaktsEndpoint) -> Optional[str]
```

A function that gets the default token for an endpoint

Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to get the token for

Returns
-------
Optional[str]
    The token for the endpoint, or None if there is no token

## Config Objects

```python
class Config()
```

Pydantic Config

