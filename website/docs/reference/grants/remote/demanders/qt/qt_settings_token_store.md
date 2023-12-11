---
sidebar_label: qt_settings_token_store
title: grants.remote.demanders.qt.qt_settings_token_store
---

## EndpointDefaults Objects

```python
class EndpointDefaults(BaseModel)
```

A serialization helper for the
default token store

## QTSettingTokenStore Objects

```python
class QTSettingTokenStore(BaseModel)
```

Retrieves and stores users matching the currently
active fakts grant

#### settings

The settings to use to store the tokens

#### save\_key

The key to use to store the tokens

#### aput\_default\_token\_for\_endpoint

```python
async def aput_default_token_for_endpoint(endpoint: FaktsEndpoint,
                                          token: str) -> None
```

A function that puts the default token for an endpoint
from the settings

Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to put the token for
token : str
    The token to put, or None to delete the token

#### aget\_default\_token\_for\_endpoint

```python
async def aget_default_token_for_endpoint(
        endpoint: FaktsEndpoint) -> Optional[str]
```

A function that gets the default token for an endpoint
from the settings

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

Pydantic config

