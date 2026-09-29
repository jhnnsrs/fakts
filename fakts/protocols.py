from typing import Dict, Any, Union, Protocol, runtime_checkable

from fakts.models import ActiveFakts


NestedFaktValue = Union[str, int, float, bool, None, Dict[str, Any], list[Any]]


FaktValue = Union[str, int, float, bool, None, Dict[str, NestedFaktValue], list[NestedFaktValue]]


@runtime_checkable
class FaktsGrant(Protocol):
    """FaktsGrant

    A FaktsGrant is a grant that can be used to load service configuration
    from a specific source. It can be used to load configuration
    from a file, from a remote endpoint, from a database, etc.

    A grant MAY also expose a ``requires_user_interaction: bool`` attribute,
    which decides whether the client is allowed to recover a dead session by
    re-running it unattended. Re-running an *interactive* grant opens a
    browser and makes the server replace the app's registration — severing
    every sibling process sharing the credential — so that only ever happens
    when a person asked for it. Grants that read a file or redeem a
    provisioning token carry no such cost and should set it to ``False``;
    that is what keeps headless deployments alive past the refresh-token
    lifetime.

    It is deliberately not a declared protocol member: this is a
    ``runtime_checkable`` Protocol, and adding a data member would make
    ``isinstance`` reject every existing grant that predates it. A grant that
    stays silent is assumed to need a human, which is the safe default.
    """

    async def aload(self) -> ActiveFakts:
        """Loads the configuration from the grant

        Depending on the grant, this function may load the configuration
        from a file, from a remote endpoint, from a database, etc. The
        implementation of the grant determines how the configuration
        is loaded, generally from preconfigured values on the grant.

        Returns
        -------
        ActiveFakts
            The configuration loaded from the grant.

        Raises
        ------
        GrantError
            If the grant failed to load the configuration.
        """
        ...


@runtime_checkable
class FaktsCache(Protocol):
    """FaktsCache

    A FaktsCache stores a loaded configuration so it can be reused across
    runs without re-querying the grant. It can be backed by a file or any
    other persistent store.
    """

    async def aload(self) -> ActiveFakts | None:
        """Loads the cached configuration

        Returns the previously cached configuration, or ``None`` if nothing
        is cached or the cache is no longer valid (e.g. expired or stale).

        Returns
        -------
        ActiveFakts | None
            The cached configuration, or ``None`` if unavailable.
        """
        ...

    async def aset(self, value: ActiveFakts) -> None:
        """Stores the configuration in the cache

        Persists the given configuration so it can later be retrieved by
        :meth:`aload`.

        Parameters
        ----------
        value : ActiveFakts
            The configuration to cache.
        """
        ...

    async def areset(self) -> None:
        """Resets the cache

        This function is used to reset the cache
        """
        ...
