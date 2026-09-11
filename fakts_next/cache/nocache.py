from typing import Optional
from fakts_next.models import ActiveFakts
from fakts_next.protocols import FaktsCache


class NoCache(FaktsCache):
    """A cache implementation that does not store any data."""

    async def aload(self) -> Optional[ActiveFakts]:
        """Loads the configuration from the grant

        It will try to load the configuration from the cache file.
        If the cache is expired, or the hash value is different from
        the one in the cache, it will load the grant again.

        Parameters
        ----------
        request : FaktsRequest
            The request object that may contain additional information needed for loading the configuration.

        Returns
        -------
        dict
            The configuration loaded from the grant.


        """

        return None

    async def aset(self, value: ActiveFakts) -> None:
        """Refreshes the configuration from the grant

        This function is used to refresh the configuration from the grant.
        This is used to refresh the configuration from the grant, and should
        be used to refresh the configuration from the grant.

        The request object is used to pass information
        """

        pass

    async def areset(self) -> None:
        """Resets the cache

        This function is used to reset the cache.
        This is used to reset the cache, and should
        be used to reset the cache.

        The request object is used to pass information
        """

        pass
