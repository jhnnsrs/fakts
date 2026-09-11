"""Fakts package.

Fakts is an asynchronous configuration and service-discovery client for
dynamic client-server deployments (it powers app configuration in the
Arkitekt ecosystem).

An app describes itself with a :class:`Manifest` (identifier, version,
scopes and the services it requires). A *grant* then obtains the active
configuration — typically from a Fakts server through the remote protocol
(discover the endpoint, demand a token, claim the configuration) — and
:class:`Fakts` resolves each required service to a working :class:`Alias`,
caches the result, and hands out OAuth2 tokens.

Quickstart:
    ```python
    from fakts_next import build_device_code_fakts, Manifest, Requirement

    fakts = build_device_code_fakts(
        url="http://localhost:8000",
        manifest=Manifest(
            identifier="my-app",
            version="0.1.0",
            scopes=["openid"],
            requirements=[
                Requirement(key="rekuest", service="live.arkitekt.rekuest"),
            ],
        ),
    )

    async with fakts:
        alias = await fakts.aget_alias("rekuest")
        token = await fakts.aget_token()
    ```
"""

from .fakts import Fakts, FaktsGrant, get_current_fakts_next
from .errors import (
    AliasNotFoundError,
    CompositionError,
    FaktsError,
    NotEnteredError,
    ServiceNotGrantedError,
)
from .cache.file import FileCache
from .cache.nocache import NoCache
from .grants import EnvGrant, GrantError, RemoteGrant
from .grants.remote.builders import build_device_code_fakts, build_redeem_fakts
from .helpers import afakt, fakt
from .models import (
    ActiveFakts,
    Alias,
    ChallengeKey,
    GrantStatus,
    Manifest,
    Requirement,
)


__all__ = [
    "Fakts",
    "FaktsGrant",
    "EnvGrant",
    "GrantError",
    "RemoteGrant",
    "get_current_fakts_next",
    "FaktsError",
    "CompositionError",
    "AliasNotFoundError",
    "ServiceNotGrantedError",
    "NotEnteredError",
    "ActiveFakts",
    "Alias",
    "ChallengeKey",
    "GrantStatus",
    "Manifest",
    "Requirement",
    "FileCache",
    "NoCache",
    "build_device_code_fakts",
    "build_redeem_fakts",
    "afakt",
    "fakt",
]
