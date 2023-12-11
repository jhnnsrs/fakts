"""Fakts package.

Fakts is a configuration management library. It allows you to
load configuration from different sources and use it in your
application.

In comparison to other configuration management libraries, Fakts
is designed to be used in an async environment, or with primarily
async grants (e.g. a database). It also allows you to use multiple
grants at the same time, and will merge the results together.

Fakts comes also with a few remote grants, that allow you to connect
to a remote configuration server, and fetch the configuration from
there, and follows a similar design the oauth2 protocol, to allow for
safe and secure configuration management.

"""


from .fakts import Fakts, FaktsGrant, get_current_fakts
from .errors import FaktsError
from .grants import EnvGrant, GrantError


__all__ = [
    "Fakts",
    "Fakt",
    "FaktsGrant",
    "EnvGrant",
    "GrantError",
    "get_current_fakts",
    "FaktsError",
]
