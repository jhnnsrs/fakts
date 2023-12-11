from typing import Optional, runtime_checkable, Protocol
from pydantic import BaseModel, Field

import logging
import asyncio
from fakts.grants.remote.types import FaktsEndpoint
from fakts.grants.remote.types import Discovery
from fakts.types import FaktsRequest


logger = logging.getLogger(__name__)


@runtime_checkable
class EndpointStore(Protocol):
    """A protocol for storing an endpoint

    This should be implemented and provided by the developer,
    and finds an implementation in the the qt package.

    We strictly separate the storage and user interaction from
    the discovery process.

    """

    async def aget_default_endpoint(self) -> Optional[FaktsEndpoint]:
        """Gets the default endpoint

        Should get the default endpoint from the storage
        Should return None if there is no default endpoint

        Returns
        -------
        Optional[FaktsEndpoint]
            The (stored) default endpoint
        """
        ...

    async def aput_default_endpoint(self, endpoint: Optional[FaktsEndpoint]) -> None:
        """Puts the default endpoint

        Should store the default endpoint in the storage
        Should remove the default endpoint if endpoint is None

        Parameters
        ----------
        endpoint : Optional[FaktsEndpoint]
            The (stored) default endpoint
        """

        ...


@runtime_checkable
class AutoSaveDecider(Protocol):
    """Should ask the user if he wants to save the endpoint

    This should be implemented and provided by the developer,
    e,g as a widget in the qt package.

    """

    async def ashould_we_save(self, endpoint: FaktsEndpoint) -> bool:
        """Should ask the user if he wants to save the endpoint



        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to save

        Returns
        -------
        bool
            Should we save the endpoint as a default?
        """
        ...


class StaticDecider(BaseModel):
    """A decider that always returns the same value"""

    allow_save: bool = True

    async def ashould_we_save(self, endpoint: FaktsEndpoint) -> bool:
        """Will always return the same value (allow_save)"""
        return self.allow_save


class AutoSaveDiscovery(BaseModel):
    """Auto save discovery

    This is a wrapper around a discovery that will ask the user if he wants to
    use a previously saved default endpoint, and only delegate to the passed discovery if
    the user does not want to use the default endpoint.

    This is useful for example for a login widget, that will ask the user if he wants to
    use the previously saved endpoint, and only delegate to the passed discovery if
    the user does not want to use the default endpoint.

    """

    store: EndpointStore
    """this is the login widget (protocol)"""

    decider: AutoSaveDecider = Field(default_factory=lambda: StaticDecider())
    """this is the login widget (protocol)"""

    discovery: Discovery
    """The grant to use for the login flow."""

    async def adiscover(self, request: FaktsRequest) -> FaktsEndpoint:
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
            if request.context.get("delete_active", True):
                await self.store.aput_default_endpoint(None)

            if request.context.get("allow_auto_discover", True):
                stored_endpoint = await self.store.aget_default_endpoint()
                if stored_endpoint:
                    logger.debug("Using stored endpoint")
                    # Lets check if the token is still valid
                    return stored_endpoint

                    # This time with a refresh

            # We are skipping the widget and just fetching the token

            logger.debug("Discovering endpoint with attached discovery")
            endpoint = await self.discovery.adiscover(request)
            logger.debug("Discovered endpoint")
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
        """pydantic config"""

        underscore_attrs_are_private = True
        arbitrary_types_allowed = True
