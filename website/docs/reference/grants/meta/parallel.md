---
sidebar_label: parallel
title: grants.meta.parallel
---

## ParallelGrant Objects

```python
class ParallelGrant(BaseModel)
```

A grant that loads multiple grants in parallel and merges the results


Attributes
----------
grants : List[FaktsGrant]
    The grants to load in parallel

omit_exceptions : bool
    Omit exceptions if any of the grants fail to load (otherwise will raise an exception)

#### grants

The grants to load in parallel

#### omit\_exceptions

Omit exceptions if any of the grants fail to load

#### aload

```python
async def aload(request: FaktsRequest) -> Dict[str, FaktValue]
```

Loads the configuration from the grants in parallel

This method will load the configuration from the grants in parallel, and merge the results, updating
the configuration with the results from each grant.

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

