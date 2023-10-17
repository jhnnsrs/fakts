import os
from typing import Dict, Optional
import pydantic
import logging
import json
from .types import Token
import logging

from fakts.grants.remote.types import FaktsEndpoint

logger = logging.getLogger(__name__)
from typing import Dict, Optional

import json
from pydantic import BaseModel
from .types import Token

logger = logging.getLogger(__name__)
from fakts.grants.remote.types import FaktsEndpoint


class EndpointDefaults(BaseModel):
    default_token: Dict[str, Token] = {}


class AutoSaveCacheStore(BaseModel):
    """Retrieves and stores users matching the currently
    active fakts grant"""

    cache_file: str = ".fakts_cache.json"

    def read_from_cache(self) -> EndpointDefaults:
        if not os.path.exists(self.cache_file):
            with open(self.cache_file, "w") as f:
                f.write(EndpointDefaults().json())

        with open(self.cache_file, "r") as f:
            x = json.loads(f.read())
            try:
                cache = EndpointDefaults(**x)
                return cache
            except pydantic.ValidationError as e:
                logger.error(f"Could not load cache file: {e}. Ignoring it")
                return EndpointDefaults()

    def write_to_cache(self, cache: EndpointDefaults):
        with open(self.cache_file, "w") as f:
            f.write(cache.json())

    async def aput_default_token_for_endpoint(
        self, endpoint: FaktsEndpoint, token: Token
    ) -> None:
        storage = self.read_from_cache()
        if token is None:
            if endpoint.base_url in storage.default_token:
                del storage.default_token[endpoint.base_url]
        else:
            storage.default_token[endpoint.base_url] = token

        self.write_to_cache(storage)

    async def aget_default_token_for_endpoint(
        self, endpoint: FaktsEndpoint
    ) -> Optional[FaktsEndpoint]:
        ...

        storage = self.read_from_cache()
        if endpoint.base_url in storage.default_token:
            return storage.default_token[endpoint.base_url]

        return None

    class Config:
        arbitrary_types_allowed = True
