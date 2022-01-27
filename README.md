# fakts

[![codecov](https://codecov.io/gh/jhnnsrs/fakts/branch/master/graph/badge.svg?token=UGXEA2THBV)](https://codecov.io/gh/jhnnsrs/fakts)
[![PyPI version](https://badge.fury.io/py/fakts.svg)](https://pypi.org/project/fakts/)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://pypi.org/project/fakts/)
![Maintainer](https://img.shields.io/badge/maintainer-jhnnsrs-blue)
[![PyPI pyversions](https://img.shields.io/pypi/pyversions/fakts.svg)](https://pypi.python.org/pypi/fakts/)
[![PyPI status](https://img.shields.io/pypi/status/fakts.svg)](https://pypi.python.org/pypi/fakts/)
[![PyPI download day](https://img.shields.io/pypi/dm/fakts.svg)](https://pypi.python.org/pypi/fakts/)

### DEVELOPMENT

## Inspiration

Fakts tries to make the setup process between client - dynamic server relations as easy as possible.

## Client - Dynamic Server

In this relation the configuration of the server is unbeknownst to the client, that means which network
address it can connect to retrieve its initial configuration. As both client and server need to trust
each other this is a complex scenario to secure. Therefore fakts provided different grants to ensure different
levels of security.

## Simple grant

In the fakts grants, fakts simply advertises itself on the network through UDP broadcasts and sends standardized configuration
to the client. In this scenario no specific configuration on a per app basis is possible, as every client that chooses to connect to the
server will receive the same configuration.

### Server

```bash
fakts serve fakts.yaml
```

### Client

```bash
fakts init
```

This flow however can be secured by a password that needs to be entered, once the client wants to retrieve configuration.

### Server

```bash
fakts serve fakts.yaml --password="*******"
```

## Advanced grant

In an oauth2 redirect like manner, fakts can also be used to advocate an endpoint that the app can then connect to in order to receive
specialised configuration through a redirect back to the client.

### Beacon

```bash
fakts beacon "http://localhost:3000/beacon"
```

### Client

```bash
fakts init --client="napari"
```

In this scenario the client will open a webbrowser with the query parameters set to the init params (in addition to a state to combat redirect attacks, and a redirect_uri) and
wait for a redirect to its redirect_uri on localhost with the configuration in the query params
