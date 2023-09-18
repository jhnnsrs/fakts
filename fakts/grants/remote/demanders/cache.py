import os
from typing import Any, Dict, Optional
import pydantic
import datetime
import logging
import json
from .types import Token
from fakts import Fakts
import logging
from qtpy import QtCore

from fakts.grants.remote.types import FaktsEndpoint

logger = logging.getLogger(__name__)
from typing import List, Dict, Optional

import json
from pydantic import BaseModel, Field
from .types import Token

logger = logging.getLogger(__name__)
from fakts.grants.remote.types import Demander, FaktsEndpoint


class EndpointDefaults(BaseModel):
    default_token: Dict[str, Token] = {}


class AutoSaveCacheStore(BaseModel):
    """Retrieves and stores users matching the currently
    active fakts grant"""

    cache_file: str = ".fakts_cache.json"

    def read_from_cache(self) -> EndpointDefaults:
        if not os.path.exists(self.cache_file):
            with open(self.cache_file, "w+") as f:
                json.dump(EndpointDefaults().json(), f)

        with open(self.cache_file, "r") as f:
            x = json.load(f)
            try:
                cache = EndpointDefaults(**x)
                return cache
            except pydantic.ValidationError as e:
                logger.error(f"Could not load cache file: {e}. Ignoring it")
                return EndpointDefaults()

    def write_to_cache(self, cache: EndpointDefaults):
        with open(self.cache_file, "w+") as f:
            json.dump(json.loads(cache.json()), f)

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
