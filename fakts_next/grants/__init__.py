"""Fakts grants module.

This module contains the grants that are included with
the fakts_next package.

Grants are the way to get configuration from different
sources. They are the main way to get configuration, and
are used by the Fakts class to get the configuration.

Generally, the grants are split into a few categories:

- Remote grants: These grants are used to connect to
    remote configuration servers, and fetch the configuration
    from there. They are generally used to fetch dynamic
    configuration from a remote server.
- Hard grants: These grants are used to
    hardcode the configuration into the code. They are
    generally used for testing purposes, or to provide
    a default configuration that can be used if no other
    configuration is available.

"""

from .env import EnvGrant
from .errors import GrantError
from .remote import RemoteGrant


__all__ = [
    "EnvGrant",
    "GrantError",
    "RemoteGrant",
]
