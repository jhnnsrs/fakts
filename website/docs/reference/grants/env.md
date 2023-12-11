---
sidebar_label: env
title: grants.env
---

#### nested\_set

```python
def nested_set(dic: Dict[str, Any], keys: List[str], value: Any) -> None
```

Sets a value in a nested dictionary (inplace version)

Parameters
----------
dic : Dict
    The dictionary to set the value in
keys : List[str]
    The keys to set the value in
value : Any
    The value to set

## EnvGrant Objects

```python
class EnvGrant(BaseModel)
```

Extras a configuration tree from the current environment
variables.

It will load all the environment variables that start with the `prepend` string,
and will parse them as a configuration tree (splitting the key by the `delimiter`)
it will also convert the keys to lowercase.

 E.g.

    ```env
    FAKTS_GROUP_NAME__KEY_NAME=value
    FAKTS_OTHER__KEY_NAME2=value2
    ```
    ```python

    grant = EnvGrant(delimiter__="__", prepend="FAKTS_") # the default values

    with Fakts(grant=grants) as fakts:
        config = grant.get() # accessing the config
        print(config["group_name"]["key_name"]) # value

        print(grant.get("other.key_name2") # value2
    ```
    ```

#### aload

```python
async def aload(request: FaktsRequest) -> Dict[str, FaktValue]
```

Loads the configuration from the environment variables.

It will load all the environment variables that start with the `prepend` string,
and will parse them as a configuration tree (splitting the key by the `delimiter`)

E.g.

```env
FAKTS_GROUP_NAME__KEY_NAME=value
FAKTS_OTHER__KEY_NAME2=value2
```
```python

grant = EnvGrant(delimiter__="__", prepend="FAKTS_") # the default values

with Fakts(grant=grants) as fakts:
    config = grant.get() # accessing the config
    print(config["group_name"]["key_name"]) # value

    print(grant.get("other.key_name2") # value2
```

Returns
-------
Dict[str, FaktValue]
    The loaded fakts

Raises
------
GrantError
    If the environment variables could not be loaded, because
    of a nested key that is not a dictionary.

