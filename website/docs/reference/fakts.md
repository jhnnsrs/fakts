---
sidebar_label: fakts
title: fakts
---

## Fakts Objects

```python
class Fakts(KoiledModel)
```

Fakts is any asynchronous configuration loader.

Fakts provides a way to concurrently load and access configuration from different
sources in async and sync environments.

It is used to load configuration from a grant, and to access it in async
and sync code.

A grant constitutes the way to load configuration. It can be a local config file
(eg. yaml, toml, json), environemnt variables, a remote configuration (eg. from
a fakts server) a database, or any other source.  It will be loaded either on
call to `load`,  or on  a call to `get` (if auto_load is set to true).

Additionaly you can compose grants with the help of meta grants in order to
load configuration from multiple sources.

**Example**:

    ```python
    async with Fakts(grant=YamlGrant("config.yaml")) as fakts:
        config = await fakts.aget("group_name")
    ```
  
  or
  
    ```python
    with Fakts(grant=YamlGrant("config.yaml")) as fakts:
        config = await fakts.get("group_name")
    ```
  
  Fakts should be used as a context manager, and will set the current fakts context
  variable to itself, letting you access the current fakts instance from anywhere in
  your code (async or sync). To understand how the async sync code access work,
  please check out the documentation for koil.
  
  

**Example**:

    ```python
    async with Fakts(grant=FailsafeGrant(
        grants=[
            EnvGrant(),
            YamlGrant("config.yaml")
        ]
    )) as fakts:
        config = await fakts.get("group_name")
    ```
  In this example fakts will load the configuration from the environment
  variables first, and if that fails, it will load it from the yaml file.

#### grant

The grant to load the configuration from

#### hard\_fakts

Hard fakts are fakts that are set by the user and cannot be overwritten by grants

#### loaded\_fakts

The currently loaded fakts. Please use `get` to access the fakts

#### allow\_auto\_load

Should we autoload the grants on a call to get?

#### load\_on\_enter

Should we load on connect?

#### delete\_on\_exit

Should we delete on connect?

#### aget

```python
async def aget(group_name: Optional[str] = None, **kwargs) -> FaktValue
```

Get Fakt Value (async)

Gets the currently active configuration for the group_name, by loading it from
the grant if it is not already loaded.

Steps:
1. Acquire lock
2. If not yet loaded and auto_load is True, load
4. Return groups fakts

**Arguments**:

- `group_name` _str_ - The group name in the fakts
- `auto_load` _bool, optional_ - Should we autoload the configuration
  if nothing has been set? Defaults to True.
- `force_refresh` _bool, optional_ - Should we force a refresh of the grants.
  Grants can decide their own refresh logic?
  Defaults to False.
  

**Returns**:

- `dict` - The active fakts

#### has\_changed

```python
def has_changed(value: FaktValue, group: str) -> bool
```

Has Changed

Checks if the value has changed since the last load.


Parameters
----------
value: FaktValue
    The value to check
group : str
    The group it belongs to

Returns
-------
bool
    True if the value has changed, False otherwise

#### arefresh

```python
async def arefresh(**kwargs) -> Dict[str, Any]
```

Causes a Refresh, by reloading the grants

#### get

```python
def get(group_name: Optional[str] = None, **kwargs) -> FaktValue
```

Get Fakt Value (Sync)

Gets the currently active configuration for the group_name, by loading it from
the grant if it is not already loaded.

Steps:
1. Acquire lock
2. If not yet loaded and auto_load is True, load
4. Return groups fakts

**Arguments**:

- `group_name` _str_ - The group name in the fakts
- `auto_load` _bool, optional_ - Should we autoload the configuration
  if nothing has been set? Defaults to True.
- `force_refresh` _bool, optional_ - Should we force a refresh of the grants.
  Grants can decide their own refresh logic?
  Defaults to False.
  

**Returns**:

- `dict` - The active fakts

#### aload

```python
async def aload(request: FaktsRequest) -> Dict[str, FaktValue]
```

Loads the configuration from the grant (async)

This method will load the configuration from the grant, and set it as the
the currently active configuration. It is called automatically on a call to
`get` if the configuration has not been loaded yet.

Parameters
----------
request : FaktsRequest
    The request that is being processed.

Returns
-------

Dict[str, FaktValue]
   The loaded fakts

#### load

```python
def load(request: FaktsRequest) -> Dict[str, FaktValue]
```

Loads the configuration from the grant (sync)

This method will load the configuration from the grant, and set it as the
the currently active configuration. It is called automatically on a call to
`get` if the configuration has not been loaded yet.

Parameters
----------
request : FaktsRequest
    The request that is being processed.

Returns
-------

Dict[str, FaktValue]
   The loaded fakts

#### \_\_aenter\_\_

```python
async def __aenter__() -> "Fakts"
```

Enter the context manager

This method will set the current fakts context variable to itself,
and create locks, to make sure that only one fakt request is
processed at a time.

#### \_\_aexit\_\_

```python
async def __aexit__(*args, **kwargs) -> None
```

Exit the context manager and clean up

#### \_repr\_html\_inline\_

```python
def _repr_html_inline_() -> str
```

(Internal) HTML representation for jupyter

## Config Objects

```python
class Config()
```

Pydantic Config

#### get\_current\_fakts

```python
def get_current_fakts() -> Fakts
```

Get the current fakts instance

This method will return the current fakts instance, or raise an
exception if no fakts instance is set.

Returns
-------
Fakts
    The current fakts instance

