import os
from typing import Any, Dict, Optional
import pydantic
import datetime
import logging
import json
from fakts.types import FaktsRequest, FaktValue, FaktsGrant

logger = logging.getLogger(__name__)


class CacheFile(pydantic.BaseModel):
    """Cache file model"""

    config: Dict[str, Any]
    created: datetime.datetime
    hash: str = ""


class CacheGrant(pydantic.BaseModel):
    """Grant that caches the result of another grant

    This grant will cache the result of another grant in a file.
    It will load the grant on the first call, and then will load
    the cached version of the grant.

    Only if the cache is expired, or a "hash" value that is passed
    to the grant is different from the one in the cache, will it
    load the grant again.

    You can set the expires_in parameter to set the time in seconds
    for the cache to expire.

    FaktsRequest context parameters:
        - allow_cache: bool - whether to allow the grant to use the cache


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

    grant: FaktsGrant = pydantic.Field(..., description="The grant to cache")
    """The grant to cache"""

    cache_file: str = ".fakts_cache.json"
    """The path to the cache file"""
    hash: str = pydantic.Field(
        default_factory=lambda: "",
        description="Validating against the hash of the config",
    )
    """The hash to validate the cache against (if this value differes from the one in the cache, the grant will be reloaded)"""

    expires_in: Optional[int]
    """When should the cache expire"""

    async def aload(self, request: FaktsRequest) -> Dict[str, FaktValue]:
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

        cache = None

        if (
            os.path.exists(self.cache_file)
            and request.context.get("allow_cache", True) is True
        ):
            with open(self.cache_file, "r") as f:
                x = json.load(f)
                try:
                    cache = CacheFile(**x)

                    if self.hash and cache.hash != self.hash:
                        cache = None

                    elif self.expires_in:
                        if (
                            cache.created + datetime.timedelta(seconds=self.expires_in)
                            < datetime.datetime.now()
                        ):
                            cache = None

                except pydantic.ValidationError as e:
                    logger.error(f"Could not load cache file: {e}. Ignoring it")

        if cache is None:
            logger.info("Loading data from grant")
            data = await self.grant.aload(request)
            cache = CacheFile(
                config=data, created=datetime.datetime.now(), hash=self.hash
            )

        with open(self.cache_file, "w+") as f:
            json.dump(json.loads(cache.json()), f)

        return cache.config

    class Config:
        """A pydantic config class"""

        arbitrary_types_allowed = True
