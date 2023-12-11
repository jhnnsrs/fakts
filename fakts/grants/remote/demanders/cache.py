import os
from typing import Dict, Optional
import pydantic
import logging
import json
from pydantic import BaseModel
from fakts.grants.remote.types import FaktsEndpoint


logger = logging.getLogger(__name__)


class EndpointDefaults(BaseModel):
    """A serialization helper for the
    default token store"""

    default_token: Dict[str, str] = {}


class CacheTokenStore(BaseModel):
    """A Cache Token Store

    This token store is used to store tokens in a cache file.
    It is used by the AutoSaveDemander to cache tokens.



    """

    cache_file: str = ".fakts_cache.json"

    def _read_from_cache(self) -> EndpointDefaults:
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

    def _write_to_cache(self, cache: EndpointDefaults) -> None:
        with open(self.cache_file, "w") as f:
            f.write(cache.json())

    async def aput_default_token_for_endpoint(
        self, endpoint: FaktsEndpoint, token: Optional[str]
    ) -> None:
        """A function that puts the default token for an endpoint



        Parameters
        ----------
        endpoint : FaktsEndpoint
            _description_
        token : str
            _description_
        """

        storage = self._read_from_cache()
        if token is None:
            if endpoint.base_url in storage.default_token:
                del storage.default_token[endpoint.base_url]
        else:
            storage.default_token[endpoint.base_url] = token

        self._write_to_cache(storage)

    async def aget_default_token_for_endpoint(
        self, endpoint: FaktsEndpoint
    ) -> Optional[str]:
        """A function that gets the default token for an endpoint

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to get the token for

        Returns
        -------
        Optional[str]
            The token for the endpoint, or None if there is no token
        """

        storage = self._read_from_cache()
        if endpoint.base_url in storage.default_token:
            return storage.default_token[endpoint.base_url]

        return None

    class Config:
        """Pydantic Config"""

        arbitrary_types_allowed = True
