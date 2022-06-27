import asyncio
import contextvars
import logging
import os
import sys
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Type

import yaml
from fakts.fakt.base import Fakt
from koil import koil
from koil.composition import KoiledModel
from koil.decorators import koilable
from koil.helpers import unkoil
from pydantic import BaseModel, Field, root_validator

from fakts.errors import (
    FaktsError,
    GroupsNotFound,
    NoGrantConfigured,
    NoGrantSucessfull,
)
from fakts.grants.base import FaktsGrant
from fakts.grants.io.yaml import YamlGrant
from fakts.grants.remote.device_code import DeviceCodeGrant
from fakts.middleware.base import FaktsMiddleware
from fakts.middleware.environment.overwritten import OverwrittenEnvMiddleware
from fakts.utils import update_nested

logger = logging.getLogger(__name__)
current_fakts = contextvars.ContextVar("current_fakts")


class Fakts(KoiledModel):
    grant: FaktsGrant = Field(default_factory=DeviceCodeGrant)
    hard_fakts: Dict[str, Any] = Field(default_factory=dict, exclude=True)
    assert_groups: Set[str] = Field(default_factory=set)
    loaded_fakts: Dict[str, Any] = Field(default_factory=dict, exclude=True)
    subapp: str = ""
    fakts_path: str = "fakts.yaml"
    force_refresh: bool = False

    auto_load: bool = True
    load_on_enter: bool = False
    """Should we load on connect?"""
    delete_on_exit: bool = False
    """Should we delete on connect?"""

    _loaded: bool = False
    _lock: asyncio.Lock = None
    _fakts_path: str = ""

    @root_validator
    def validate_integrity(cls, values):

        values["fakts_path"] = (
            f'{values["subapp"]}.{values["fakts_path"]}'
            if values["subapp"]
            else values["fakts_path"]
        )

        try:
            with open(values["fakts_path"], "r") as file:
                config = yaml.load(file, Loader=yaml.FullLoader)
                values["loaded_fakts"] = update_nested(values["hard_fakts"], config)
        except:
            logger.info("Could not load fakts from file")

        if not values["loaded_fakts"] and not values["grant"]:
            raise ValueError(
                f"No grant configured and we did not find fakts at path {values['fakts_path']}. Please make sure you configure fakts correctly."
            )

        return values

    async def aget(
        self,
        group_name: str,
        bypass_middleware=False,
        auto_load=False,
    ):
        """Get Config

        Gets the currently active configuration for the group_name. This is a loop
        save function, and will guard the current fakts state through an async lock.

        Steps:
            1. Acquire lock.
            2. If not yet loaded and auto_load is True, load (reloading should be done seperatily)
            3. Pass through middleware (can be opt out by setting bypass_iddleware to True)
            4. Return groups fakts

        Args:
            group_name (str): The group name in the fakts
            bypass_middleware (bool, optional): Bypasses the Middleware (e.g. no overwrites). Defaults to False.
            auto_load (bool, optional): Should we autoload the configuration through grants if nothing has been set? Defaults to True.

        Returns:
            dict: The active fakts
        """
        assert (
            self._lock is not None
        ), "You need to enter the context first before calling this function"
        async with self._lock:
            print(self._loaded)
            if not self._loaded:
                if not self.auto_load and not auto_load:
                    raise FaktsError(
                        "Fakts not loaded, please load first. Or set auto_load to True"
                    )
                await self.aload()

        return self._getsubgroup(group_name)

    def _getsubgroup(self, group_name):
        config = {**self.loaded_fakts}

        for subgroup in group_name.split("."):
            try:
                config = config[subgroup]
            except KeyError as e:
                logger.error(f"Could't find {subgroup} in {config}")
                return {}

        return config

    def has_changed(self, fakt_dict: Dict[str, Any], group: str):
        return (
            not fakt_dict or self._getsubgroup(group) != fakt_dict
        )  # TODO: Implement Hashing on config?

    async def arefresh(self):
        self._loaded = False
        await self.aload(force_refresh=True)

    def get(self, *args, **kwargs):
        return unkoil(self.aget, *args, **kwargs)

    @property
    def healthy(self):
        if not self.loaded_fakts:
            return False
        if not self.assert_groups.issubset(set(self.loaded_fakts.keys())):
            return False
        return True

    @property
    def initial_healty(self):
        return (not self.force_refresh) and self.healthy

    async def aload(self, force_refresh=False) -> Dict[str, Any]:
        if not self.force_refresh and not force_refresh:
            if self.healthy:
                self._loaded = True
                return self.loaded_fakts

        grant_exceptions = {}
        print("We are doing this")
        self.loaded_fakts = await self.grant.aload()
        print("We are reaching this?")
        if not self.assert_groups.issubset(set(self.loaded_fakts.keys())):
            raise GroupsNotFound(
                f"Could not find {self.assert_groups - set(self.loaded_fakts.keys())}. "
            )

        if not self.loaded_fakts:
            raise NoGrantSucessfull(f"No Grants sucessfull {grant_exceptions}")

        if self.fakts_path:
            with open(self.fakts_path, "w") as file:
                yaml.dump(self.loaded_fakts, file)

        self._loaded = True
        return self.loaded_fakts

    async def adelete(self):
        self.loaded_fakts = {}
        self._loaded = False

        if self.fakts_path:
            os.remove(self.fakts_path)

    def load(self, **kwargs):
        return unkoil(self.aload, **kwargs)

    def delete(self, **kwargs):
        return unkoil(self.adelete, **kwargs)

    async def __aenter__(self):
        current_fakts.set(self)
        self._lock = asyncio.Lock()
        if self.load_on_enter:
            await self.aload()
        return self

    async def __aexit__(self, *args, **kwargs):
        if self.delete_on_exit:
            await self.adelete()
        current_fakts.set(None)

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
        json_encoders = {
            FaktsGrant: lambda x: f"Fakts Grant {x.__class__.__name__}",
        }


def get_current_fakts() -> Fakts:
    return current_fakts.get()
