from typing import Optional, runtime_checkable, Protocol
from pydantic import BaseModel, Field

import logging
import asyncio
from fakts.grants.remote.types import FaktsEndpoint
from fakts.types import FaktsRequest

from fakts.grants.remote.types import Demander

logger = logging.getLogger(__name__)


@runtime_checkable
class TokenStore(Protocol):
    """A token store is a protocol that is used to store
    tokens for endpoints."""

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
        ...

    async def aput_default_token_for_endpoint(
        self, endpoint: FaktsEndpoint, token: Optional[str]
    ) -> None:
        """A function that puts the default token for an endpoint

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to put the token for
        token : Optional[str]
            The token to put, or None to delete the token
        """
        ...


@runtime_checkable
class AutoSaveDecider(Protocol):
    """A decider that decides if we should save the token or not

    This could be for example a widget that asks the user if he wants to save
    the token or not.



    """

    async def ashould_we_save(self, endpoint: FaktsEndpoint, token: str) -> bool:
        """A function that decides if we should save the token or not

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to save the token for
        token : str
            Tbe token to save

        Returns
        -------
        bool
            True if we should save the token, False otherwise
        """
        ...


class StaticDecider(BaseModel):
    """A decider that always returns the same value"""

    allow_save: bool = True
    """The value to return"""

    async def ashould_we_save(self, endpoint: FaktsEndpoint, token: str) -> bool:
        """A function that decides if we should save the token or not

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to save the token for
        token : str
            Tbe token to save

        Returns
        -------
        bool
            True if we should save the token, False otherwise
        """
        return self.allow_save


class AutoSaveDemander(BaseModel):
    """A discovery the autosaves the
    discovered endpoint and selects it as the default one.
    """

    store: TokenStore
    """A token store to use for the saving and loading of tokens"""

    decider: AutoSaveDecider = Field(default_factory=lambda: StaticDecider())
    """ A decider to to decide if we should save the token or not"""

    demander: Demander
    """The demander to use to fetch the token if we don't have it"""

    async def ademand(self, endpoint: FaktsEndpoint, request: FaktsRequest) -> str:
        """Fetch the token for the endpoint

        This method will first try to fetch the token from the store.
        If it is not found, it will fetch it from the demander.
        If the decider decides that we should save the token, we will
        save it in the store.

        Request context parameters:
        - allow_auto_demand: If this is set to False, we will not try to
            fetch the token from the store, and will only fetch it from
            the demander.




        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to fetch the token for
        request : FaktsRequest
            The request to use for the fetching of the token

        Returns
        -------
        str
            The token for the endpoint

        Raises
        ------
        e
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
        """Config for the model"""

        underscore_attrs_are_private = True
        arbitrary_types_allowed = True
