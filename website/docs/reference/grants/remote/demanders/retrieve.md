---
sidebar_label: retrieve
title: grants.remote.demanders.retrieve
---

## RetrieveError Objects

```python
class RetrieveError(DemandError)
```

A base class for all retrieve errors

## RetrieveDemander Objects

```python
class RetrieveDemander(BaseModel)
```

Retrieve Demander

A retrieve grant is a remote grant can be used to retrieve a token and a configuration from a fakts server, by claiming to be an already
registed public application on the fakts server. Public applications are applications that are not able to keep a secret, and therefore
need users to explicitly grant them access to their data. YOu need to also provide a redirect_uri that matches the one that is registered
on the fakts server.

#### ssl\_context

An ssl context to use for the connection to the endpoint

#### manifest

The manifest of the application that is requesting the token

#### retrieve\_url

The url to use for retrieving the token (overwrited the endpoint url)

#### ademand

```python
async def ademand(endpoint: FaktsEndpoint, request: FaktsRequest) -> str
```

Demand a token from the endpoint

Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to demand the token from
request : FaktsRequest
    The request to use for the demand

Returns
-------
str
    The token that was retrieved

## Config Objects

```python
class Config()
```

Pydantic Config

