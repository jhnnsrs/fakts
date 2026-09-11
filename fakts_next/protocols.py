from typing import Dict, Any, Union, Protocol, runtime_checkable

from fakts_next.models import ActiveFakts


NestedFaktValue = Union[str, int, float, bool, None, Dict[str, Any], list[Any]]


FaktValue = Union[str, int, float, bool, None, Dict[str, NestedFaktValue], list[NestedFaktValue]]


@runtime_checkable
class FaktsGrant(Protocol):
    """FaktsGrant

    A FaktsGrant is a grant that can be used to load service configuration
    from a specific source. It can be used to load configuration
    from a file, from a remote endpoint, from a database, etc.
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
    runs without re-querying the grant. It can be backed by a file, by
    Qt settings, or any other persistent store.
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
