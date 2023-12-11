import asyncio
import contextvars
import logging
from typing import Any, Dict

from koil.composition import KoiledModel
from koil.helpers import unkoil
from pydantic import Field
from typing import Optional
from fakts.errors import GroupNotFound, NoFaktsFound

from .types import FaktsRequest, FaktValue, FaktsGrant

logger = logging.getLogger(__name__)
current_fakts: contextvars.ContextVar[Optional["Fakts"]] = contextvars.ContextVar(
    "current_fakts", default=None
)


class Fakts(KoiledModel):
    """Fakts is any asynchronous configuration loader.

    Fakts provides a way to concurrently load and access configuration from different
    sources in async and sync environments.

    It is used to load configuration from a grant, and to access it in async
    and sync code.

    A grant constitutes the way to load configuration. It can be a local config file
    (eg. yaml, toml, json), environemnt variables, a remote configuration (eg. from
    a fakts server) a database, or any other source.  It will be loaded either on
    call to `load`,  or on  a call to `get` (if auto_load is set to true).

    Additionaly you can compose grants with the help of meta grants in order to
    load configuration from multiple sources.

    Example:
        ```python
        async with Fakts(grant=YamlGrant("config.yaml")) as fakts:
            config = await fakts.aget("group_name")
        ```

        or

        ```python
        with Fakts(grant=YamlGrant("config.yaml")) as fakts:
            config = await fakts.get("group_name")
        ```

    Fakts should be used as a context manager, and will set the current fakts context
    variable to itself, letting you access the current fakts instance from anywhere in
    your code (async or sync). To understand how the async sync code access work,
    please check out the documentation for koil.


    Example:
        ```python
        async with Fakts(grant=FailsafeGrant(
            grants=[
                EnvGrant(),
                YamlGrant("config.yaml")
            ]
        )) as fakts:
            config = await fakts.get("group_name")
        ```
        In this example fakts will load the configuration from the environment
        variables first, and if that fails, it will load it from the yaml file.


    """

    grant: FaktsGrant
    """The grant to load the configuration from"""

    hard_fakts: Dict[str, Any] = Field(default_factory=dict, exclude=True)
    """Hard fakts are fakts that are set by the user and cannot be overwritten by grants"""

    loaded_fakts: Dict[str, Any] = Field(default_factory=dict, exclude=True)
    """The currently loaded fakts. Please use `get` to access the fakts"""

    allow_auto_load: bool = Field(
        default=True, description="Should we autoload on get?"
    )
    """Should we autoload the grants on a call to get?"""

    load_on_enter: bool = False
    """Should we load on connect?"""
    delete_on_exit: bool = False
    """Should we delete on connect?"""

    _loaded: bool = False
    _lock: Optional[asyncio.Lock] = None

    async def aget(
        self,
        group_name: Optional[str] = None,
        **kwargs,
    ) -> FaktValue:
        """Get Fakt Value (async)

        Gets the currently active configuration for the group_name, by loading it from
        the grant if it is not already loaded.

        Steps:
            1. Acquire lock
            2. If not yet loaded and auto_load is True, load
            4. Return groups fakts

        Args:
            group_name (str): The group name in the fakts
            auto_load (bool, optional): Should we autoload the configuration
                                        if nothing has been set? Defaults to True.
            force_refresh (bool, optional): Should we force a refresh of the grants.
                                            Grants can decide their own refresh logic?
                                            Defaults to False.

        Returns:
            dict: The active fakts
        """
        assert (
            self._lock is not None
        ), "You need to enter the context first before calling this function"
        async with self._lock:
            if not self.loaded_fakts:
                try:
                    await self.aload(FaktsRequest(context=kwargs))
                except Exception as e:
                    logger.error(e, exc_info=True)
                    raise e

        try:
            config = self._getsubgroup(group_name)
        except GroupNotFound as e:
            raise e

        return config

    def _getsubgroup(self, group_name: Optional[str] = None) -> Dict[str, Any]:
        """Get subgroup

        Protected function to get a subgroup from the loaded fakts

        Args:
            group_name (str): The name of the group

        Raises:
            GroupNotFound: If the groups is not found in the loadedfakts

        Returns:
            Dict[str, Any]: The subgroups configuration as a dictioniary
        """
        config = {**self.loaded_fakts}

        if group_name is None:
            return config

        for subgroup in group_name.split("."):
            try:
                config = config[subgroup]
            except KeyError as e:
                raise GroupNotFound(f"Could't find {subgroup} in fakts {config}") from e

        return config

    def has_changed(self, value: FaktValue, group: str) -> bool:
        """Has Changed

        Checks if the value has changed since the last load.


        Parameters
        ----------
        value: FaktValue
            The value to check
        group : str
            The group it belongs to

        Returns
        -------
        bool
            True if the value has changed, False otherwise
        """

        return (
            not value or self._getsubgroup(group) != value
        )  # TODO: Implement Hashing on config?

    async def arefresh(self, **kwargs) -> Dict[str, Any]:
        """Causes a Refresh, by reloading the grants"""
        self.loaded_fakts = {}
        await self.aload(FaktsRequest(context=kwargs, is_refresh=True))
        return self.loaded_fakts

    def get(
        self,
        group_name: Optional[str] = None,
        **kwargs,
    ) -> FaktValue:
        """Get Fakt Value (Sync)

        Gets the currently active configuration for the group_name, by loading it from
        the grant if it is not already loaded.

        Steps:
            1. Acquire lock
            2. If not yet loaded and auto_load is True, load
            4. Return groups fakts

        Args:
            group_name (str): The group name in the fakts
            auto_load (bool, optional): Should we autoload the configuration
                                        if nothing has been set? Defaults to True.
            force_refresh (bool, optional): Should we force a refresh of the grants.
                                            Grants can decide their own refresh logic?
                                            Defaults to False.

        Returns:
            dict: The active fakts
        """
        return unkoil(self.aget, group_name=group_name, **kwargs)

    async def aload(self, request: FaktsRequest) -> Dict[str, FaktValue]:
        """Loads the configuration from the grant (async)

        This method will load the configuration from the grant, and set it as the
        the currently active configuration. It is called automatically on a call to
        `get` if the configuration has not been loaded yet.

        Parameters
        ----------
        request : FaktsRequest
            The request that is being processed.

        Returns
        -------

        Dict[str, FaktValue]
           The loaded fakts


        """
        self.loaded_fakts = await self.grant.aload(request)
        self._loaded = True
        return self.loaded_fakts

    def load(self, request: FaktsRequest) -> Dict[str, FaktValue]:
        """Loads the configuration from the grant (sync)

        This method will load the configuration from the grant, and set it as the
        the currently active configuration. It is called automatically on a call to
        `get` if the configuration has not been loaded yet.

        Parameters
        ----------
        request : FaktsRequest
            The request that is being processed.

        Returns
        -------

        Dict[str, FaktValue]
           The loaded fakts


        """
        return unkoil(self.aload, request)

    async def __aenter__(self) -> "Fakts":
        """Enter the context manager

        This method will set the current fakts context variable to itself,
        and create locks, to make sure that only one fakt request is
        processed at a time.
        """

        current_fakts.set(
            self
        )  # TODO: We should set tokens, but depending on async/sync this is shit
        self._lock = asyncio.Lock()
        return self

    async def __aexit__(self, *args, **kwargs) -> None:
        """Exit the context manager and clean up"""
        current_fakts.set(
            None
        )  # TODO: And here we should reset, but can't because of koil unsafe thread

    def _repr_html_inline_(self) -> str:
        """(Internal) HTML representation for jupyter"""
        return f"<table><tr><td>grant</td><td>{self.grant.__class__.__name__}</td></tr></table>"

    class Config:
        """Pydantic Config"""

        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
        json_encoders = {
            FaktsGrant: lambda x: f"Fakts Grant {x.__class__.__name__}",  # we don't want to serialize the grant when we save the fakts
        }


def get_current_fakts() -> Fakts:
    """Get the current fakts instance

    This method will return the current fakts instance, or raise an
    exception if no fakts instance is set.

    Returns
    -------
    Fakts
        The current fakts instance
    """
    fakts = current_fakts.get()

    if fakts is None:
        raise NoFaktsFound("No fakts instance set in this context")

    return fakts
