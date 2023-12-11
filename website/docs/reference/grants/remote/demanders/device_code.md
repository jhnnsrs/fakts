---
sidebar_label: device_code
title: grants.remote.demanders.device_code
---

## DeviceCodeError Objects

```python
class DeviceCodeError(DemandError)
```

A base class for all device code errors

## DeviceCodeTimeoutError Objects

```python
class DeviceCodeTimeoutError(DeviceCodeError)
```

An error that is raised when the timeout for the device code grant is reached

## ClientKind Objects

```python
class ClientKind(str, Enum)
```

The kind of client that you want to request

#### DEVELOPMENT

Tries to set up a development client (client belongs to user)

#### WEBSITE

Tries to set up a website client (allows for the client to be used by anyone)

## DeviceCodeDemander Objects

```python
class DeviceCodeDemander(BaseModel)
```

Device Code Grant

The device code grant is a remote grant that is able to newly establish an application
on the fakts server server that support the device code grant.

When setting up the device code grant, the user will be prompted to visit a URL and enter a code.
If open_browser is set to True, the URL will be opened in the default browser, and automatically
entered. Otherwise the user will be prompted to enter the code manually.

The device code grant will then poll the fakts server for the status of the code. If the code is
still pending, the grant will wait for a second and then poll again. If the code is granted, the
token will be returned. If the code is denied, an exception will be raised.

#### manifest

An ssl context to use for the connection to the endpoint

#### expiration\_time\_seconds

The expiration time of the token in seconds

#### redirect\_uris

The redirect uri to use for the client if it is a desktop application

#### requested\_client\_kind

The kind of client that you want to request. Check the ClientKind enum for more information

#### timeout

The timeout for the device code grant in seconds. If the timeout is reached, the grant will fail.

#### open\_browser

If set to True, the URL will be opened in the default browser (if exists). Otherwise the user will be prompted to enter the code manually.

#### check\_requested\_matches\_redirect\_uris

```python
@root_validator(allow_reuse=True)
@classmethod
def check_requested_matches_redirect_uris(
        cls: Type["DeviceCodeDemander"], values: Dict[str,
                                                      Any]) -> Dict[str, Any]
```

Validates and checks that either a schema_dsl or schema_glob is provided, or that allow_introspection is set to True

#### arequest\_code

```python
async def arequest_code(endpoint: FaktsEndpoint) -> str
```

Requests a new code from the fakts server.

This method will request a new code from the fakts server. This code will be used to
authenticate the user. The user will be prompted to visit a URL and enter the code.

Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to fetch the token for

Returns
-------
str
    The devide-code that was requested

#### ademand

```python
async def ademand(endpoint: FaktsEndpoint, request: FaktsRequest) -> str
```

Requests a token from the fakts server

This method will request a token from the fakts server, using the device code grant.
In the process, this grant will ask the fakts server to create a unique
device code, it will then ask the user to visit a URL and enter the code.

If open_browser is set to True, the URL will be opened in the default browser, and automatically
entered. Otherwise the user will be prompted to enter the code manually.

The device code grant will then poll the fakts server for the status of the code. If the code is
still pending, the grant will wait for a second and then poll again. If the code is granted, the
token will be returned. If the code is denied, an exception will be raised.

Parameters
----------
endpoint : FaktsEndpoint
    The endpoint to fetch the token for
request : FaktsRequest
    The request to use for the fetching of the token

Returns
-------
str

## Config Objects

```python
class Config()
```

Pydantic Config

