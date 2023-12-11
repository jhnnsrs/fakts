---
sidebar_label: utils
title: grants.remote.discovery.utils
---

#### check\_wellknown

```python
async def check_wellknown(url: str,
                          ssl_context: ssl.SSLContext,
                          timeout: int = 4) -> FaktsEndpoint
```

Check the well-known endpoint

This function will check the well-known endpoint and return the endpoint
if it is valid. If it is not valid, it will raise an exception.

Parameters
----------
url : str
    Url to check
ssl_context : ssl.SSLContext
    The ssl context to use for the connection
timeout : int, optional
    The timeout for the connection , by default 4

Returns
-------
FaktsEndpoint
    A valid endpoint

Raises
------
DiscoveryError

#### discover\_url

```python
async def discover_url(url: str,
                       ssl_context: ssl.SSLContext,
                       auto_protocols: Optional[List[str]] = None,
                       allow_appending_slash: bool = False,
                       timeout: int = 4) -> FaktsEndpoint
```

Discover the endpoint from the url

This function will try to discover the endpoint from the url. If the url
does not contain a protocol, it will try to use the auto protocols to
discover the endpoint.

Parameters
----------
url : str
    The (base) url to discover
ssl_context : ssl.SSLContext
    The ssl context to use for the connection
auto_protocols : Optional[List[str]], optional
    The protocols to try (e.g. http https), by default None
allow_appending_slash : bool, optional
    Should we autoappend a slash if the ur does not conain it, by default False
timeout : int, optional
    How long to wait to consider a connection not valid, by default 4

Returns
-------
FaktsEndpoint
    The endpoint

Raises
------
DiscoveryError

