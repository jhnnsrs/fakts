from typing import Type, TypeVar
from pydantic import BaseSettings
from pydantic.error_wrappers import ValidationError
import fakts
from fakts.fakts import Fakts, current_fakts


Class = TypeVar("Class")


class ConfigError(Exception):
    pass


class Config(BaseSettings):
    class Config:
        extra = "ignore"
        group = "undefined"

    @classmethod
    async def from_fakts(
        cls: Type[Class], fakts: Fakts = None, bypass_middleware=False, **overwrites
    ) -> Class:
        group = cls.__config__.group
        assert (
            group != "undefined"
        ), f"Please overwrite the Metaclass Config parameter group and point at your group {cls}"
        fakts = fakts or current_fakts.get()
        try:
            return cls(**await fakts.aget(group, bypass_middleware=bypass_middleware))
        except ValidationError as e:
            raise ConfigError(f"{fakts.loaded_fakts} was not sufficient") from e
