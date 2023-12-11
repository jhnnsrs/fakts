---
sidebar_label: cache
title: grants.meta.cache
---

## CacheFile Objects

```python
class CacheFile(pydantic.BaseModel)
```

Cache file model

## CacheGrant Objects

```python
class CacheGrant(pydantic.BaseModel)
```

Grant that caches the result of another grant

This grant will cache the result of another grant in a file.
It will load the grant on the first call, and then will load
the cached version of the grant.

Only if the cache is expired, or a &quot;hash&quot; value that is passed
to the grant is different from the one in the cache, will it
load the grant again.

You can set the expires_in parameter to set the time in seconds
for the cache to expire.

FaktsRequest context parameters:
    - allow_cache: bool - whether to allow the grant to use the cache


Attributes
----------
grant : FaktsGrant
    The grant to cache
cache_file : str
    The path to the cache file
hash : str
    The hash to validate the cache against
expires_in : Optional[int]
    The time in seconds for the cache to expire

#### grant

The grant to cache

#### cache\_file

The path to the cache file

#### hash

The hash to validate the cache against (if this value differes from the one in the cache, the grant will be reloaded)

#### expires\_in

When should the cache expire

#### aload

```python
async def aload(request: FaktsRequest) -> Dict[str, FaktValue]
```

Loads the configuration from the grant

It will try to load the configuration from the cache file.
If the cache is expired, or the hash value is different from
the one in the cache, it will load the grant again.

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

