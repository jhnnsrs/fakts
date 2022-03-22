import asyncio
import contextvars
from typing import Any, Dict, List, Optional, Set, Type

from pydantic import BaseModel, Field
from fakts.errors import (
    GroupsNotFound,
    NoGrantConfigured,
    NoGrantSucessfull,
)
from fakts.middleware.base import FaktsMiddleware
from fakts.utils import update_nested
from koil import koil
import yaml
from fakts.grants.base import FaktsGrant
import os
from fakts.grants.yaml import YamlGrant
from fakts.middleware.environment.overwritten import OverwrittenEnvMiddleware
import logging
import sys
from pydantic import root_validator
from koil.composition import KoiledModel
from koil.decorators import koilable
from koil.helpers import unkoil

logger = logging.getLogger(__name__)
current_fakts = contextvars.ContextVar("current_fakts")


class Fakts(KoiledModel):
    grants: List[FaktsGrant] = Field(default_factory=list)
    middlewares: List[FaktsMiddleware] = Field(default_factory=list)
    hard_fakts: Dict[str, Any] = Field(default_factory=dict, exclude=True)
    assert_groups: Set[str] = Field(default_factory=set)
    loaded_fakts: Dict[str, Any] = Field(default_factory=dict, exclude=True)
    subapp: str = ""
    fakts_path: str = "fakts.yaml"
    force_refresh: bool = False

    load_on_enter: bool = True
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

        if not values["loaded_fakts"] and not values["grants"]:
            raise ValueError(
                f"No grants configured and we did not find fakts at path {values['fakts_path']}. Please make sure you configure fakts correctly."
            )

        return values

    async def aget(self, group_name: str, bypass_middleware=False, auto_load=True):
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
            self._loaded
        ), "Fakts not loaded, please load first. (By entering the fakts context)"

        config = {**self.loaded_fakts}

        if not bypass_middleware:
            for middleware in self.middlewares:
                additional_config = await middleware.aparse(previous=config)
                config = update_nested(config, additional_config)

        for subgroup in group_name.split("."):
            try:
                config = config[subgroup]
            except KeyError as e:
                logger.error(f"Could't find {subgroup} in {config}")
                config = {}

        return config

    async def arefresh(self):
        await self.aload()

    def get(self, *args, **kwargs):
        return unkoil(self.aget, *args, **kwargs)

    @property
    def healthy(self):
        return (
            self.assert_groups.issubset(set(self.loaded_fakts.keys()))
            and self.loaded_fakts
        )

    async def aload(self) -> Dict[str, Any]:
        if not self.force_refresh:
            if self.healthy:
                self._loaded = True
                return self.loaded_fakts

        if len(self.grants) == 0:
            raise NoGrantConfigured(
                "Local fakts were insufficient and fakts has no grants configured. Please add a grant to your fakts instance or initialize your fakts instance with a Grant"
            )

        grant_exceptions = {}
        for grant in self.grants:
            try:
                additional_fakts = await grant.aload(previous=self.loaded_fakts)
                self.loaded_fakts = update_nested(self.loaded_fakts, additional_fakts)
            except Exception as e:
                grant_exceptions[grant.__class__.__name__] = e

        if not self.assert_groups.issubset(set(self.loaded_fakts.keys())):

            error_description = (
                f"This might be due to following exceptions in grants {grant_exceptions}"
                if grant_exceptions
                else "All Grants were sucessful. But none retrieved these keys!"
            )

            raise GroupsNotFound(
                f"Could not find {self.assert_groups - set(self.loaded_fakts.keys())}. "
                + error_description
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

        if self.fakts_path:
            os.remove(self.fakts_path)

    def load(self, **kwargs):
        return unkoil(self.aload, **kwargs)

    def delete(self, **kwargs):
        return unkoil(self.adelete, **kwargs)

    async def __aenter__(self):
        current_fakts.set(self)
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
