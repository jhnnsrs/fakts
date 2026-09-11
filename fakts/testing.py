"""In-process testing support: a Fakts you can hot-plug into the context.

:class:`TestingFakts` is a real :class:`~fakts.fakts.Fakts` — entering it
(``with`` or ``async with``) publishes it on the ``current_fakts``
contextvar exactly like production, so code under test that calls
:func:`~fakts.fakts.get_current_fakts` (or the ``fakt``/``afakt``
helpers) sees it with **no monkeypatching**, and typed consumers holding a
``Fakts`` field accept it. It differs from a production instance in exactly
two seams:

- alias challenges always pass (no live server needed), and
- token renewal hands out the configured ``tokens`` instead of calling the
  OAuth2 token endpoint — through the real lock/expiry machinery, so tests
  that exercise expiry and ``arefresh_token`` semantics exercise the true
  code path.

Build one with :func:`build_testing_fakts`::

    from fakts.testing import build_testing_fakts

    with build_testing_fakts(aliases={"alpaka": "http://testserver"}):
        ...  # get_current_fakts() now resolves, aliases and tokens work

Note that the first alias resolution itself fetches a token (the report
token — real behavior), so ``token_fetches`` is typically 1 after the first
``get_alias`` call.
"""

import time
from typing import Dict, List, Optional, Union
from urllib.parse import urlparse

from pydantic import PrivateAttr

from fakts.cache.nocache import NoCache
from fakts.fakts import Fakts
from fakts.grants.hard import HardFaktsGrant
from fakts.models import (
    ActiveFakts,
    Alias,
    AuthFakt,
    ChallengeKey,
    GrantStatus,
    Instance,
    Manifest,
    Requirement,
    SelfFakt,
)

__all__ = ["TestingFakts", "build_testing_fakts"]


class TestingFakts(Fakts):
    """A Fakts whose aliases always resolve and whose tokens come from a list.

    ``tokens`` are handed out in order by the token-renewal seam; the last
    one repeats once the list is exhausted. ``token_lifetime`` controls when
    a handed-out token expires: ``None`` means never (one fetch serves the
    whole session), ``0`` means immediately (every ``aget_token()`` call
    renews — the shape for testing per-request refresh). ``token_fetches``
    counts renewals for assertions.
    """

    tokens: List[str] = ["test-token"]
    token_lifetime: Optional[float] = None

    _token_index: int = PrivateAttr(default=0)

    @property
    def token_fetches(self) -> int:
        """How many times a token was fetched through the renewal seam."""
        return self._token_index

    async def achallenge_alias(
        self, alias: Alias, challenge_key: Optional[ChallengeKey] = None
    ) -> bool:
        """Every alias is reachable in tests."""
        return True

    async def _afetch_token(self, interactive: bool = False) -> str:
        # Contract inherited from Fakts._afetch_token: runs while the caller
        # holds _token_lock (take nothing, call no public token method) and
        # must leave loaded_token and _token_expires_at consistent.
        token = self.tokens[min(self._token_index, len(self.tokens) - 1)]
        self._token_index += 1
        self.loaded_token = token
        self._token_expires_at = (
            time.time() + self.token_lifetime
            if self.token_lifetime is not None
            else None
        )
        return token


def _parse_alias(key: str, value: Union[str, Alias]) -> Alias:
    """Coerce a URL string like ``"http://testserver"`` into an Alias."""
    if isinstance(value, Alias):
        return value
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(
            f"Alias for '{key}' must be an Alias or a URL with scheme and "
            f"host (e.g. 'http://testserver'), got {value!r}"
        )
    return Alias(
        id=key,
        host=parsed.hostname,
        port=parsed.port,
        ssl=parsed.scheme == "https",
        path=parsed.path.strip("/") or None,
    )


def build_testing_fakts(
    aliases: Dict[str, Union[str, Alias]],
    *,
    tokens: Optional[List[str]] = None,
    token: str = "test-token",
    token_lifetime: Optional[float] = None,
    deployment_name: str = "testing",
) -> TestingFakts:
    """Build a :class:`TestingFakts` from a service→URL mapping.

    ``aliases`` maps fakts keys to either URL strings or full ``Alias``
    models; each key becomes both a manifest requirement and a granted
    instance, so ``get_alias(key)`` resolves without kwargs. ``tokens``
    (or the single ``token``) and ``token_lifetime`` are handed to
    :class:`TestingFakts` unchanged.

    The embedded auth points at a ``.invalid`` token endpoint: if anything
    escapes the testing seams and performs a real refresh, it fails loudly
    instead of silently talking to a server.
    """
    resolved = {key: _parse_alias(key, value) for key, value in aliases.items()}

    payload = ActiveFakts(
        self=SelfFakt(
            deployment_name=deployment_name,
            alias=Alias(id="self", host="fakts-testing.invalid"),
        ),
        auth=AuthFakt(
            client_id="testing",
            token_endpoint="http://fakts-testing.invalid/token",
            refresh_token="testing-refresh-token",
            report_endpoint=None,
            access_token=None,
        ),
        instances={
            key: Instance(
                service=f"testing.{key}", identifier=f"testing.{key}", aliases=[alias]
            )
            for key, alias in resolved.items()
        },
        statuses={key: GrantStatus.GRANTED for key in resolved},
    )

    return TestingFakts(
        grant=HardFaktsGrant(fakts=payload),
        manifest=Manifest(
            identifier="fakts-testing",
            version="0.0.1",
            scopes=["openid"],
            requirements=[
                Requirement(key=key, service=f"testing.{key}") for key in resolved
            ],
        ),
        cache=NoCache(),
        tokens=tokens if tokens is not None else [token],
        token_lifetime=token_lifetime,
    )
