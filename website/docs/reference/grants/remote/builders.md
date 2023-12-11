---
sidebar_label: builders
title: grants.remote.builders
---

#### build\_remote\_testing

```python
def build_remote_testing(value: Dict[str, FaktValue]) -> RemoteGrant
```

Builds a remote grant for testing purposes

Will always return the same value when claiming.

Parameters
----------
value : Dict[str, FaktValue]
    The value to return when claiming

Returns
-------
RemoteGrant
    The remote grant

