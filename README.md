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

Fakts was designed to make configuration of apps compatible with concurrency pattern, it is designed to allow
for asynchronous retrieval of configuration from various sources, may it be a config file, environmental variables
or a remote server.

# Core Design

Fakts uses Grants to obtain configuration asynchronously, a grant is a way of retrieving the configuration from a
specific source. It can be a local config file (eg. yaml, toml, json), environemnt variables, a remote configuration (eg. from a fakts server), a database.
The fakts class then wraps the grant to ensure both a sychronous and asychronous interface that is threadsafe.

Grants are designed to be composable through MetaGrants so by desigining a specifc grant structure, one can
highly customize the retrieval logic. Please check out the

# Example:

```python
async with Fakts(grant=YamlGrant("config.yaml")) as fakts:
    config = await fakts.aget("group_name")
```

or

```python
with Fakts(grant=YamlGrant("config.yaml")) as fakts:
    config = fakts.get("group_name")
```

Fakts should be used as a context manager, and will set the current fakts context variable to itself, letting
you access the current fakts instance from anywhere in your code (async or sync) without specifically passing a referece.
To understand how the async sync code access work, please check out the documentation for koil.

# Composability

You can compose grants through meta grants in order to load configuration from multiple sources (eg. a local, file
that can be overwritten by a remote configuration, or some envionment variables).

Example:

```python
async with Fakts(grant=FailsafeGrant(
    grants=[
        EnvGrant(),
        YamlGrant("config.yaml")
    ]
)) as fakts:
    config = await fakts.get("group_name")
```

In this example fakts will load the configuration from the environment variables first, and if that fails,
it will load it from the yaml file.

## Special Use Case: Dynamic Server Relations

Fakts provides the remote grant protocol for retrieval of configuration in dynamic client-server relationships.
With these grants you provide a software manifest for a configuration server (fakts-server), that then grants
the configuration (either through user approval (similar to device code grant)). These grants are mainly used
to setup or claim an oauth2 application on the backend securely that then can be used to identify the application in the
future. These grants are at the moment highly specific to the arkitekt platform and subject to change.

# Sister packages

These packages provide contrib modules to support auto
configuration through a fakts instance

- herre: oauth2 client
- rath: graphql client (typed through turms)
