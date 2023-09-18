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
from .types import Token
from fakts.grants.remote.types import Demander

logger = logging.getLogger(__name__)


@runtime_checkable
class TokenStore(Protocol):
    async def aget_default_token_for_endpoint(
        self, endpoint: FaktsEndpoint
    ) -> Optional[FaktsEndpoint]:
        ...

    async def aput_default_token_for_endpoint(
        self, endpoint: FaktsEndpoint, token: Token
    ) -> None:
        ...


@runtime_checkable
class AutoSaveDecider(Protocol):
    async def ashould_we_save(self, endpoint: FaktsEndpoint, token: Token) -> bool:
        """Should ask the user if he wants to save the endpoint"""
        ...


class StaticDecider(BaseModel):
    allow_save: bool = True

    async def ashould_we_save(self, endpoint: FaktsEndpoint, token: Token) -> bool:
        return self.allow_save


class AutoSaveDemander(BaseModel):
    """A discovery the autosaves the
    discovered endpoint and selects it as the default one.



    """

    store: TokenStore
    """this is the login widget (protocol)"""

    decider: AutoSaveDecider = Field(default_factory=lambda: StaticDecider())
    """this is the login widget (protocol)"""

    demander: Demander
    """The grant to use for the login flow."""

    async def ademand(
        self, endpoint: FaktsEndpoint, request: FaktsRequest
    ) -> FaktsEndpoint:
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
            if request.context.get("allow_auto_demand", True):
                token = await self.store.aget_default_token_for_endpoint(endpoint)
                if token:
                    # Lets check if the token is still valid
                    return token

                    # This time with a refresh

            # We are skipping the widget and just fetching the token

            token = await self.demander.ademand(endpoint, request)
            should_we_save = await self.decider.ashould_we_save(endpoint, token)
            if should_we_save:
                await self.store.aput_default_token_for_endpoint(endpoint, token)
            else:
                await self.store.aput_default_token_for_endpoint(endpoint, None)

            return token

        except asyncio.CancelledError as e:
            raise e

        except Exception as e:
            logger.error(e, exc_info=True)
            raise e

    class Config:
        underscore_attrs_are_private = True
        arbitrary_types_allowed = True
