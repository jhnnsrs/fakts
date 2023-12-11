---
sidebar_label: post
title: grants.remote.claimers.post
---

## ClaimEndpointClaimer Objects

```python
class ClaimEndpointClaimer(BaseModel)
```

A claimer that claims the configuration from the endpoint

This claimer is used to claim the configuration from the endpoint.
This is the default claimer, and it is used by the default
Remote Grants.

#### ssl\_context

An ssl context to use for the connection to the endpoint

#### aclaim

```python
async def aclaim(token: str, endpoint: FaktsEndpoint,
                 request: FaktsRequest) -> Dict[str, FaktValue]
```

Claims the configuration from the endpoint

Parameters
----------
token : str
    The token to use to claim the configuration
endpoint : FaktsEndpoint
    The endpoint to claim the configuration from
request : FaktsRequest
    The request to use to claim the configuration

Returns
-------
Dict[str, FaktValue]
    The configuration

Raises
------
ClaimError
    An error occured while claiming the configuration

## Config Objects

```python
class Config()
```

A pydantic config class

