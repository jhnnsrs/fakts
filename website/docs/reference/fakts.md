---
sidebar_label: fakts
title: fakts
---

## Fakts Objects

```python
class Fakts(KoiledModel)
```

#### load\_on\_enter

Should we load on connect?

#### delete\_on\_exit

Should we delete on connect?

#### aget

```python
async def aget(group_name: str, bypass_middleware=False, auto_load=False, validate: BaseModel = None)
```

Get Config

Gets the currently active configuration for the group_name. This is a loop
save function, and will guard the current fakts state through an async lock.

Steps:
1. Acquire lock.
2. If not yet loaded and auto_load is True, load (reloading should be done seperatily)
3. Pass through middleware (can be opt out by setting bypass_iddleware to True)
4. Return groups fakts

**Arguments**:

- `group_name` _str_ - The group name in the fakts
- `bypass_middleware` _bool, optional_ - Bypasses the Middleware (e.g. no overwrites). Defaults to False.
- `auto_load` _bool, optional_ - Should we autoload the configuration through grants if nothing has been set? Defaults to True.
  

**Returns**:

- `dict` - The active fakts

