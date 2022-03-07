import asyncio
import contextvars
from typing import List, Type
from fakts.errors import (
    GroupsNotFound,
    NoFaktsFound,
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

from koil.decorators import koilable
from koil.helpers import unkoil

logger = logging.getLogger(__name__)
current_fakts = contextvars.ContextVar("current_fakts")


@koilable(add_connectors=True)
class Fakts:
    def __init__(
        self,
        *args,
        grants=[],
        middlewares=[],
        assert_groups=[],
        fakts_path="fakts.yaml",
        subapp: str = None,
        hard_fakts={},
        force_refresh=False,
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
        self.force_refresh = force_refresh
        self.loaded = False

        try:
            with open(self.fakts_path, "r") as file:
                config = yaml.load(file, Loader=yaml.FullLoader)
                self.fakts = update_nested(self.hard_fakts, config)
        except Exception as e:
            print(e)
            logger.info("No fakts file found. We will have to use grants!")

        if self.force_refresh:
            self.fakts = {}

        if not self.fakts:
            assert (
                len(self.grants) >= 1
            ), f"No grants configured and we did not find fakts at path {self.fakts_path}. Please make sure you configure fakts correctly."

        for grant in self.grants:
            assert hasattr(grant, "aload"), "Grant must have an aload method"
            assert not isinstance(grant, type), "SHould not be a class"

        print(f"Fakts are {self.fakts}")

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
            self.loaded
        ), "Fakts not loaded, please load first. (By entering the fakts context)"

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
        return unkoil(self.aget, *args, **kwargs)

    @property
    def healthy(self):
        return self.assert_groups.issubset(set(self.fakts.keys()))

    async def aload(self):
        if not self.force_refresh:
            if self.healthy:
                self.loaded = True
                return

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
                grant_exceptions[grant.__class__.__name__] = e

        print(grant_exceptions)
        if not self.assert_groups.issubset(set(self.fakts.keys())):

            error_description = (
                f"This might be due to following exceptions in grants {grant_exceptions}"
                if grant_exceptions
                else "All Grants were sucessful. But none retrieved these keys!"
            )

            raise GroupsNotFound(
                f"Could not find {self.assert_groups - set(self.fakts.keys())}. "
                + error_description
            )

        if not self.fakts:
            raise NoGrantSucessfull(f"No Grants sucessfull {grant_exceptions}")

        if self.fakts_path:
            with open(self.fakts_path, "w") as file:
                yaml.dump(self.fakts, file)

        self.loaded = True

    async def adelete(self):
        self.fakts = {}

        if self.fakts_path:
            os.remove(self.fakts_path)

    def load(self, **kwargs):
        return unkoil(self.aload, **kwargs)

    def delete(self, **kwargs):
        return unkoil(self.adelete, **kwargs)

    async def __aenter__(self):
        self._token = current_fakts.set(self)
        await self.aload()
        return self

    async def __aexit__(self, *args, **kwargs):
        current_fakts.reset(self._token)
