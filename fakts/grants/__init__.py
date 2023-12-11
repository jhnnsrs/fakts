""" Fakts grants module.

This module contains the grants that are included with
the fakts package.

Grants are the way to get configuration from different
sources. They are the main way to get configuration, and
are used by the Fakts class to get the configuration.

Generally, the grants are split into a few categories:

- IO grants: These grants are used to read configuration
    from files, and are generally used to read static
    configuration from files.
- Remote grants: These grants are used to connect to
    remote configuration servers, and fetch the configuration
    from there. They are generally used to fetch dynamic
    configuration from a remote server.
- Meta grants: These grants are used to combine multiple
    grants together, and are generally used to combine
    multiple grants together, to get configuration from
    multiple sources at the same time.
- Save grants: These grants are used to  load
    the configuration from another grant and cache it
    on disk, so that it can be used later without
    having to fetch it again.
- Env grants: These grants are used to load configuration
    from environment variables.


"""


from .env import EnvGrant
from .errors import GrantError
from .meta import FailsafeGrant, ParallelGrant, CacheGrant
from .remote import RemoteGrant


__all__ = [
    "EnvGrant",
    "GrantError",
    "FaktsGrant",
    "YamlGrant",
    "FailsafeGrant",
    "ParallelGrant",
    "CacheGrant",
    "RemoteGrant",
]
