---
sidebar_label: toml
title: grants.io.toml
---

## TomlGrant Objects

```python
class TomlGrant(FaktsGrant)
```

A class used to represent a Grant in a TOML file.

Attributes
----------
filepath : str
    a formatted string to print out the file path where the TOML file is located

Methods
-------
aload(request: FaktsRequest)
    Asynchronously loads the TOML file and returns the configuration.

#### aload

```python
async def aload(request: FaktsRequest) -> Dict[str, FaktValue]
```

Loads the TOML file and returns the configuration.

Parameters
----------
request : FaktsRequest
    The request object that may contain additional information needed for loading the TOML file.

Returns
-------
dict
    The configuration loaded from the TOML file.

## Config Objects

```python
class Config()
```

A pydantic config class

