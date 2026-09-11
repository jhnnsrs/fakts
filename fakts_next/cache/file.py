import os
from typing import Optional
import pydantic
import datetime
import logging
import json
from fakts_next.models import ActiveFakts

logger = logging.getLogger(__name__)


class CacheFile(pydantic.BaseModel):
    """Cache file model"""

    fakts: ActiveFakts
    created: datetime.datetime
    hash: str = ""


class FileCache(pydantic.BaseModel):
    """Grant that caches the result of another grant

    This grant will cache the result of another grant in a file.
    It will load the grant on the first call, and then will load
    the cached version of the grant.

    Only if the cache is expired, or a "hash" value that is passed
    to the grant is different from the one in the cache, will it
    load the grant again.

    You can set the expires_in parameter to set the time in seconds
    for the cache to expire.

    Note that the default cache file path is *relative to the current
    working directory*: running the same app from a different directory
    will silently miss the cache (and re-run the grant), and two different
    apps run from the same directory will fight over the same file (their
    differing hashes invalidate each other on every run). Use an absolute,
    per-app cache path to avoid both.


    Attributes
    ----------
    grant : FaktsGrant
        The grant to cache
    cache_file : str
        The path to the cache file
    hash : str
        The hash to validate the cache against
    expires_in : Optional[int]
        The time in seconds for the cache to expire


    """

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    """The grant to cache"""

    cache_file: str = ".fakts_cache.json"
    """The path to the cache file"""
    hash: str = pydantic.Field(
        default_factory=lambda: "",
        description="Validating against the hash of the config",
    )
    """The hash to validate the cache against (if this value differes from the one in the cache, the grant will be reloaded)"""

    expires_in: Optional[int] = None
    """When should the cache expire"""

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

        if not os.path.exists(self.cache_file):
            return None

        try:
            with open(self.cache_file, "r") as f:
                x = json.load(f)
            cache = CacheFile(**x)
        except (json.JSONDecodeError, pydantic.ValidationError, OSError) as e:
            # A corrupt or unreadable cache should never break startup:
            # treat it as a cache miss and let the grant reload.
            logger.error(f"Could not load cache file: {e}. Ignoring it")
            return None

        if self.hash and cache.hash != self.hash:
            return None

        if self.expires_in:
            if cache.created + datetime.timedelta(seconds=self.expires_in) < datetime.datetime.now():
                return None

        return cache.fakts

    async def aset(self, value: ActiveFakts) -> None:
        """Refreshes the configuration from the grant

        This function is used to refresh the configuration from the grant.
        This is used to refresh the configuration from the grant, and should
        be used to refresh the configuration from the grant.

        The request object is used to pass information
        """

        cache = CacheFile(fakts=value, created=datetime.datetime.now(), hash=self.hash)

        # Write atomically (temp file + rename), so a crash mid-write or a
        # concurrent writer can never leave a corrupt cache file behind.
        tmp_file = f"{self.cache_file}.{os.getpid()}.tmp"
        with open(tmp_file, "w") as f:
            f.write(cache.model_dump_json())
        os.replace(tmp_file, self.cache_file)

    async def areset(self) -> None:
        """Resets the cache

        This function is used to reset the cache.
        This is used to reset the cache, and should
        be used to reset the cache.

        The request object is used to pass information
        """

        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
        return None
