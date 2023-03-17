import asyncio
import contextvars
import logging
from typing import Any, Dict, Set

from koil.composition import KoiledModel
from koil.helpers import unkoil
from pydantic import Field

from fakts.errors import FaktsError, GroupNotFound
from fakts.grants.base import FaktsGrant

logger = logging.getLogger(__name__)
current_fakts: contextvars.ContextVar["Fakts"] = contextvars.ContextVar("current_fakts")


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

    assert_groups: Set[str] = Field(default_factory=set)
    """Asserted groups are groups that are asserted to be present in the fakts. If 
    they are not present, an error will be raised"""

    allow_auto_load: bool = Field(
        default=True, description="Should we autoload on get?"
    )
    """Should we autoload the grants on a call to get?"""

    load_on_enter: bool = False
    """Should we load on connect?"""
    delete_on_exit: bool = False
    """Should we delete on connect?"""

    _loaded: bool = False
    _lock: asyncio.Lock = None
    _fakts_path: str = ""

    async def aget(
        self,
        group_name: str,
        auto_load=True,
        force_refresh=False,
    ):
        """Get Config

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
            if not self.loaded_fakts or force_refresh:
                if self.allow_auto_load and auto_load:
                    await self.aload(force_refresh=force_refresh)
                else:
                    raise FaktsError(
                        "No loaded fakts and auto_load is False. Please load first."
                    )

        try:
            config = self._getsubgroup(group_name)
        except GroupNotFound as e:
            if self.allow_auto_load and auto_load:
                await self.aload(force_refresh=True)
                config = self._getsubgroup(group_name)
            else:
                raise e
            

        return config

    def _getsubgroup(self, group_name: str) -> Dict[str, Any]:
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

        for subgroup in group_name.split("."):
            try:
                config = config[subgroup]
            except KeyError as e:
                raise GroupNotFound(f"Could't find {subgroup} in fakts {config}") from e

        return config

    def has_changed(self, fakt_dict: Dict[str, Any], group: str):
        return (
            not fakt_dict or self._getsubgroup(group) != fakt_dict
        )  # TODO: Implement Hashing on config?

    async def arefresh(self):
        """Causes a Refresh on the grants. Grants can decide their own refresh logic."""
        self.loaded_fakts = None
        await self.aload(force_refresh=True)

    def get(self, *args, **kwargs):
        """Sync version of aget"""
        return unkoil(self.aget, *args, **kwargs)

    async def aload(self, force_refresh=False) -> Dict[str, Any]:
        """Loads the configuration from the grant and asserts the groups"""

        self.loaded_fakts = await self.grant.aload(force_refresh=force_refresh)
        if not self.assert_groups.issubset(set(self.loaded_fakts.keys())):
            raise GroupNotFound(
                f"Expected Configuration for {self.assert_groups - set(self.loaded_fakts.keys())}. "
            )

        self._loaded = True
        return self.loaded_fakts

    def load(self, **kwargs):
        """Sync version of aloads"""
        return unkoil(self.aload, **kwargs)

    async def __aenter__(self):

        current_fakts.set(self)
        self._lock = asyncio.Lock()
        if self.load_on_enter:
            await self.aload()
        return self

    async def __aexit__(self, *args, **kwargs):
        current_fakts.set(None)

    def _repr_html_inline_(self):
        return f"<table><tr><td>grant</td><td>{self.grant.__class__.__name__}</td></tr></table>"

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
        json_encoders = {
            FaktsGrant: lambda x: f"Fakts Grant {x.__class__.__name__}",
        }


def get_current_fakts() -> Fakts:
    return current_fakts.get()
