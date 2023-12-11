---
sidebar_label: well_known
title: grants.remote.discovery.well_known
---

## WellKnownDiscovery Objects

```python
class WellKnownDiscovery(BaseModel)
```

A discovery that uses the well-known endpoint

A well-known endpoint is a special endpoint that is used to discover
the actual endpoint. This is useful for example in scenarious where the
fakts server might change its location, and the client needs to find it,
easily.

This discovery mechanism also provides ways to configure the discovery
process, such as the timeout, the ssl context, and the protocols to try
if no protocol is specified in the url.

#### url

The url of the well-known endpoint

#### ssl\_context

An ssl context to use for the connection to the endpoint

#### allow\_appending\_slash

If the url does not end with a slash, should we append one? A well-known endpoint should end with a slash

#### auto\_protocols

If no protocol is specified, we will try to connect to the following protocols

#### timeout

A timeout for the connection to the well-known endpoint. Applies to each protocol

#### adiscover

```python
async def adiscover(request: FaktsRequest) -> FaktsEndpoint
```

Discover the endpoint

This method will try to discover the endpoint using the well-known
endpoint. It will try to connect to the well-known endpoint using
the protocols specified in the configuration, and the timeout
specified in the configuration.

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

