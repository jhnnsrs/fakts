import os
from typing import Optional
import pydantic
import logging
import json
from pydantic import BaseModel
from fakts.grants.remote.types import FaktsEndpoint


logger = logging.getLogger(__name__)


class AutoSaveCacheStore(BaseModel):
    """An implementation of EndpointStore that stores the endpoint in a file

    This is a simple implementation that stores the endpoint in a file.
    And will be used if no other implementation is found.



    """

    cache_file: str = ".endpoint_cache.json"

    def _read_from_cache(self) -> Optional[FaktsEndpoint]:
        if not os.path.exists(self.cache_file):
            return None

        with open(self.cache_file, "r") as f:
            x = json.loads(f.read())
            try:
                cache = FaktsEndpoint(**x)
                return cache
            except pydantic.ValidationError as e:
                logger.error(f"Could not load cache file: {e}. Ignoring it")
                return None

    def _write_to_cache(self, endpoint: Optional[FaktsEndpoint]) -> None:
        if endpoint is None:
            os.path.remove(self.cache_file)  # type: ignore
            return

        with open(self.cache_file, "w") as f:
            f.write(endpoint.json())

    async def aput_default_endpoint(self, endpoint: Optional[FaktsEndpoint]) -> None:
        """Puts the default endpoint

        Stores the endpoint in the cache file

        Parameters
        ----------
        endpoint : Optional[FaktsEndpoint]
            The (stored) default endpoint
        """
        self._write_to_cache(endpoint)

    async def aget_default_endpoint(
        self,
    ) -> Optional[FaktsEndpoint]:
        """Gets the default endpoint

        Gets the endpoint from the cache file

        Returns
        -------
        Optional[FaktsEndpoint]
            The (stored) default endpoint
        """
        ...

        return self._read_from_cache()

    class Config:
        """Pydantic config"""

        arbitrary_types_allowed = True
