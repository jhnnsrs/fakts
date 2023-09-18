from typing import Any, Dict, List, Optional, Type, runtime_checkable, Protocol
from pydantic import BaseModel, Field, SecretStr

import ssl
import certifi
import aiohttp
import logging
import asyncio
from fakts.grants.remote.types import FaktsEndpoint
from herre.fetcher.types import UserFetcher
from fakts.grants.remote.types import Discovery
from fakts.types import FaktsRequest


logger = logging.getLogger(__name__)


@runtime_checkable
class EndpointStore(Protocol):
    async def aget_default_endpoint(self) -> Optional[FaktsEndpoint]:
        ...

    async def aput_default_endpoint(self, endpoint: FaktsEndpoint) -> None:
        ...


@runtime_checkable
class AutoSaveDecider(Protocol):
    async def ashould_we_save(self, endpoint: FaktsEndpoint) -> bool:
        """Should ask the user if he wants to save the endpoint"""
        ...


class StaticDecider(BaseModel):
    allow_save: bool = True

    async def ashould_we_save(self, *args, **kwargs) -> bool:
        return self.allow_save


class AutoSaveDiscovery(BaseModel):
    """A discovery the autosaves the
    discovered endpoint and selects it as the default one.



    """

    store: EndpointStore
    """this is the login widget (protocol)"""

    decider: AutoSaveDecider = Field(default_factory=lambda: StaticDecider())
    """this is the login widget (protocol)"""

    discovery: Discovery
    """The grant to use for the login flow."""

    async def discover(self, request: FaktsRequest) -> FaktsEndpoint:
        """Fetches the token

        This function will only delegate to the grant if the user has not
        previously logged in (aka there is no token in the storage) Or if the
        force_refresh flag is set.

        Args:
            force_refresh (bool, optional): _description_. Defaults to False.

        Raises:
            e: _description_

        Returns:
            Token: _description_
        """

        try:
            if request.context.get("allow_auto_discover", True):
                stored_endpoint: EndpointStore = (
                    await self.store.aget_default_endpoint()
                )
                if stored_endpoint:
                    print("Discovered stored enpoint", stored_endpoint)
                    # Lets check if the token is still valid
                    return stored_endpoint

                    # This time with a refresh

            # We are skipping the widget and just fetching the token

            print("Discovering endpoint", request)
            endpoint = await self.discovery.discover(request)
            print("Discovered endpoint", endpoint)
            should_we_save = await self.decider.ashould_we_save(endpoint)
            if should_we_save:
                await self.store.aput_default_endpoint(endpoint)
            else:
                await self.store.aput_default_endpoint(None)

            return endpoint

        except asyncio.CancelledError as e:
            raise e

        except Exception as e:
            logger.error(e, exc_info=True)
            raise e

    class Config:
        underscore_attrs_are_private = True
        arbitrary_types_allowed = True
