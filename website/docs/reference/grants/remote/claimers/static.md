---
sidebar_label: static
title: grants.remote.claimers.static
---

## StaticClaimer Objects

```python
class StaticClaimer(BaseModel)
```

A claimer that always claims
the same configuration

This is mostly used for testing purposes.

#### value

An ssl context to use for the connection to the endpoint

#### aclaim

```python
async def aclaim(token: str, endpoint: FaktsEndpoint,
                 request: FaktsRequest) -> Dict[str, FaktValue]
```

Claim the configuration from the endpoint

