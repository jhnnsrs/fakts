---
sidebar_label: auto_save
title: grants.remote.discovery.auto_save
---

## EndpointStore Objects

```python
@runtime_checkable
class EndpointStore(Protocol)
```

A protocol for storing an endpoint

This should be implemented and provided by the developer,
and finds an implementation in the the qt package.

We strictly separate the storage and user interaction from
the discovery process.

#### aget\_default\_endpoint

```python
async def aget_default_endpoint() -> Optional[FaktsEndpoint]
```

Gets the default endpoint

Should get the default endpoint from the storage
Should return None if there is no default endpoint

Returns
-------
Optional[FaktsEndpoint]
    The (stored) default endpoint

#### aput\_default\_endpoint

```python
async def aput_default_endpoint(endpoint: Optional[FaktsEndpoint]) -> None
```

Puts the default endpoint

Should store the default endpoint in the storage
Should remove the default endpoint if endpoint is None

Parameters
----------
endpoint : Optional[FaktsEndpoint]
    The (stored) default endpoint

## AutoSaveDecider Objects

```python
@runtime_checkable
class AutoSaveDecider(Protocol)
```

Should ask the user if he wants to save the endpoint

This should be implemented and provided by the developer,
e,g as a widget in the qt package.

#### ashould\_we\_save

```python
async def ashould_we_save(endpoint: FaktsEndpoint) -> bool
```

Should ask the user if he wants to save the endpoint



Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to save

Returns
-------
bool
    Should we save the endpoint as a default?

## StaticDecider Objects

```python
class StaticDecider(BaseModel)
```

A decider that always returns the same value

#### ashould\_we\_save

```python
async def ashould_we_save(endpoint: FaktsEndpoint) -> bool
```

Will always return the same value (allow_save)

## AutoSaveDiscovery Objects

```python
class AutoSaveDiscovery(BaseModel)
```

Auto save discovery

This is a wrapper around a discovery that will ask the user if he wants to
use a previously saved default endpoint, and only delegate to the passed discovery if
the user does not want to use the default endpoint.

This is useful for example for a login widget, that will ask the user if he wants to
use the previously saved endpoint, and only delegate to the passed discovery if
the user does not want to use the default endpoint.

#### store

this is the login widget (protocol)

#### decider

this is the login widget (protocol)

#### discovery

The grant to use for the login flow.

#### adiscover

```python
async def adiscover(request: FaktsRequest) -> FaktsEndpoint
```

Fetches the token

This function will only delegate to the grant if the user has not
previously logged in (aka there is no token in the storage) Or if the
force_refresh flag is set.

**Arguments**:

- `force_refresh` _bool, optional_ - _description_. Defaults to False.
  

**Raises**:

- `e` - _description_
  

**Returns**:

- `Token` - _description_

## Config Objects

```python
class Config()
```

pydantic config

