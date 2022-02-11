import asyncio
import contextvars
from typing import List
from fakts.errors import GroupsNotFound, NoFaktsFound, NoGrantConfigured
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

logger = logging.getLogger(__name__)


class Fakts:
    def __init__(
        self,
        *args,
        grants=[],
        middlewares=[],
        assert_groups=[],
        fakts_path="fakts.yaml",
        register=True,
        subapp: str = None,
        hard_fakts={},
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.grants: List[FaktsGrant] = grants
        self.middlewares: List[FaktsMiddleware] = middlewares
        self.hard_fakts = hard_fakts
        self.fakts = {}
        self.assert_groups = set(assert_groups)
        self.subapp = subapp
        self.fakts_path = f"{subapp}.{fakts_path}" if subapp else fakts_path
        self._lock = None

        if register:
            set_global_fakts(self)

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

        if not self._lock:
            self._lock = asyncio.Lock()

        async with self._lock:
            if not self.fakts:
                await self.aload()

        config = {**self.fakts}

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
        return koil(self.aget(*args, **kwargs), **kwargs)

    async def aload(self, force_refresh=False):

        self.fakts = {}

        if not force_refresh:
            try:
                with open(self.fakts_path, "r") as file:
                    config = yaml.load(file, Loader=yaml.FullLoader)
                    self.fakts = update_nested(self.hard_fakts, config)

                if self.assert_groups.issubset(set(self.fakts.keys())):
                    # Configuration is valid, we can load it
                    return self.fakts

            except:
                pass

        if len(self.grants) == 0:
            raise NoGrantConfigured(
                "Local fakts were insufficient and fakts has no grants configured. Please add a grant to your fakts instance or initialize your fakts instance with a Grant"
            )

        grant_exceptions = {}
        for grant in self.grants:
            try:
                additional_fakts = await grant.aload(previous=self.fakts)
                self.fakts = update_nested(self.fakts, additional_fakts)
            except Exception as e:
                grant_exceptions.add(e)

        if not self.assert_groups.issubset(set(self.fakts.keys())):

            error_description = (
                "This might be due to following exceptions in grants {grant_exceptions}"
                if grant_exceptions
                else "All Grants were sucessful. But none retrieved these keys!"
            )

            raise GroupsNotFound(
                f"Could not find {self.assert_groups - set(self.fakts.keys())}. "
                + error_description
            )

        if self.fakts_path:
            with open(self.fakts_path, "w") as file:
                yaml.dump(self.fakts, file)

        return self.fakts

    async def adelete(self):
        self.fakts = {}

        if self.fakts_path:
            os.remove(self.fakts_path)

    def load(self, **kwargs):
        return koil(self.aload(), **kwargs)

    def delete(self, **kwargs):
        return koil(self.adelete(), **kwargs)

    def __enter__(self):
        current_fakts.set(self)
        return self

    def __exit__(self, *args, **kwargs):
        current_fakts.set(None)


current_fakts = contextvars.ContextVar("current_fakts", default=None)
GLOBAL_FAKTS = None


def set_global_fakts(fakts):
    global GLOBAL_FAKTS
    GLOBAL_FAKTS = fakts


def get_current_fakts(allow_global=True, creation_kwargs={}):

    fakts = current_fakts.get()
    if fakts:
        return fakts

    if not allow_global:
        raise NoFaktsFound("No current fakts found and global fakts are not allowed")

    if GLOBAL_FAKTS:
        return GLOBAL_FAKTS

    if os.getenv("FAKTS_ALLOW_GLOBAL_DEFAULT", "True") == "True":
        set_global_fakts(Fakts(**creation_kwargs))
        return GLOBAL_FAKTS

    return GLOBAL_FAKTS
