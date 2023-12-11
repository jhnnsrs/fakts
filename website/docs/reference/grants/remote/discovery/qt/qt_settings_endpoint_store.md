---
sidebar_label: qt_settings_endpoint_store
title: grants.remote.discovery.qt.qt_settings_endpoint_store
---

## QtSettingsEndpointStore Objects

```python
class QtSettingsEndpointStore(BaseModel)
```

Retrieves and stores users matching the currently
active fakts grant

#### aput\_default\_endpoint

```python
async def aput_default_endpoint(endpoint: Optional[FaktsEndpoint]) -> None
```

A function that stores the default endpoint

Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to put

#### aget\_default\_endpoint

```python
async def aget_default_endpoint() -> Optional[FaktsEndpoint]
```

A function that gets the default endpoint

Returns
-------
Optional[FaktsEndpoint]
    The stored endpoint, or None if there is no endpoint

## Config Objects

```python
class Config()
```

Pydantic Config

