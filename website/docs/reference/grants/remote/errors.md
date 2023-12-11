---
sidebar_label: errors
title: grants.remote.errors
---

## RemoteGrantError Objects

```python
class RemoteGrantError(GrantError)
```

Base class for all remotegrant errors

## ClaimError Objects

```python
class ClaimError(RemoteGrantError)
```

An error that occurs when claiming the configuration from the endpoint

## DiscoveryError Objects

```python
class DiscoveryError(RemoteGrantError)
```

An error that occurs when discovering the endpoint

## DemandError Objects

```python
class DemandError(RemoteGrantError)
```

An error that occurs when demanding the token from the endpoint

