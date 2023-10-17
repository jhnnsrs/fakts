import os
from typing import Optional
import pydantic
import logging
import json
import logging

from fakts.grants.remote.types import FaktsEndpoint

logger = logging.getLogger(__name__)
from typing import Optional

import json
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from fakts.grants.remote.types import FaktsEndpoint


class AutoSaveCacheStore(BaseModel):
    """Retrieves and stores users matching the currently
    active fakts grant"""

    cache_file: str = ".endpoint_cache.json"

    def read_from_cache(self) -> FaktsEndpoint:
        if not os.path.exists(self.cache_file):
            return None

        with open(self.cache_file, "r") as f:
            x = json.load(f.read())
            try:
                cache = FaktsEndpoint(**x)
                return cache
            except pydantic.ValidationError as e:
                logger.error(f"Could not load cache file: {e}. Ignoring it")
                return None

    def write_to_cache(self, endpoint: Optional[FaktsEndpoint]):
        if endpoint is None:
            os.path.remove(self.cache_file)
            return

        with open(self.cache_file, "w") as f:
            f.write(endpoint.json())

    async def aput_default_endpoint(self, endpoint: Optional[FaktsEndpoint]) -> None:
        self.write_to_cache(endpoint)

    async def aget_default_endpoint(
        self,
    ) -> Optional[FaktsEndpoint]:
        ...

        return self.read_from_cache()

    class Config:
        arbitrary_types_allowed = True
