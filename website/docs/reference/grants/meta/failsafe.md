---
sidebar_label: failsafe
title: grants.meta.failsafe
---

## FailsafeGrant Objects

```python
class FailsafeGrant(BaseModel)
```

Represent a Grant that loads configuration from a selection
of other grants. It will try to load the grants in order,
and will return the values from the first grant that succeeds.

#### aload

```python
async def aload(request: FaktsRequest) -> Dict[str, FaktValue]
```

Loads the configuration from the grant

It will try to load the grants in order, and will return the values from the first grant that succeeds.


Parameters
----------
request : FaktsRequest
    The request object that may contain additional information needed for loading the configuration.

Returns
-------
dict
    The configuration loaded from the grant.

## Config Objects

```python
class Config()
```

A pydantic config class

