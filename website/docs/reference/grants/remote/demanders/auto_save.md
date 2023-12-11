---
sidebar_label: auto_save
title: grants.remote.demanders.auto_save
---

## TokenStore Objects

```python
@runtime_checkable
class TokenStore(Protocol)
```

A token store is a protocol that is used to store
tokens for endpoints.

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

#### aput\_default\_token\_for\_endpoint

```python
async def aput_default_token_for_endpoint(endpoint: FaktsEndpoint,
                                          token: Optional[str]) -> None
```

A function that puts the default token for an endpoint

Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to put the token for
token : Optional[str]
    The token to put, or None to delete the token

## AutoSaveDecider Objects

```python
@runtime_checkable
class AutoSaveDecider(Protocol)
```

A decider that decides if we should save the token or not

This could be for example a widget that asks the user if he wants to save
the token or not.

#### ashould\_we\_save

```python
async def ashould_we_save(endpoint: FaktsEndpoint, token: str) -> bool
```

A function that decides if we should save the token or not

Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to save the token for
token : str
    Tbe token to save

Returns
-------
bool
    True if we should save the token, False otherwise

## StaticDecider Objects

```python
class StaticDecider(BaseModel)
```

A decider that always returns the same value

#### allow\_save

The value to return

#### ashould\_we\_save

```python
async def ashould_we_save(endpoint: FaktsEndpoint, token: str) -> bool
```

A function that decides if we should save the token or not

Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to save the token for
token : str
    Tbe token to save

Returns
-------
bool
    True if we should save the token, False otherwise

## AutoSaveDemander Objects

```python
class AutoSaveDemander(BaseModel)
```

A discovery the autosaves the
discovered endpoint and selects it as the default one.

#### store

A token store to use for the saving and loading of tokens

#### decider

A decider to to decide if we should save the token or not

#### demander

The demander to use to fetch the token if we don&#x27;t have it

#### ademand

```python
async def ademand(endpoint: FaktsEndpoint, request: FaktsRequest) -> str
```

Fetch the token for the endpoint

This method will first try to fetch the token from the store.
If it is not found, it will fetch it from the demander.
If the decider decides that we should save the token, we will
save it in the store.

Request context parameters:
- allow_auto_demand: If this is set to False, we will not try to
    fetch the token from the store, and will only fetch it from
    the demander.




Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to fetch the token for
request : FaktsRequest
    The request to use for the fetching of the token

Returns
-------
str
    The token for the endpoint

Raises
------
e

## Config Objects

```python
class Config()
```

Config for the model

