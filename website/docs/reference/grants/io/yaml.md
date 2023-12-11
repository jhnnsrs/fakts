---
sidebar_label: yaml
title: grants.io.yaml
---

## YamlGrant Objects

```python
class YamlGrant(BaseModel)
```

Represent a Grant that loads configuration from a YAML file.

Attributes
----------
filepath : str
    The path of the YAML file.

#### aload

```python
async def aload(request: FaktsRequest) -> Dict[str, FaktValue]
```

Loads the YAML file and returns the configuration.

## Config Objects

```python
class Config()
```

A pydantic config class

