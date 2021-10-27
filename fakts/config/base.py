from typing import Type, TypeVar
from pydantic import BaseSettings
import fakts
from fakts.fakts import Fakts, get_current_fakts


Class = TypeVar("Class")

class Config(BaseSettings):

    class Config:
        extra = "ignore"
        group = "undefined"


    @classmethod
    def from_fakts(cls: Type[Class], fakts: Fakts = None, **overwrites) -> Class:
        group = cls.__config__.group
        assert group != "undefined", f"Please overwrite the Metaclass Config parameter group and point at your group {cls}"
        fakts = fakts or get_current_fakts()
        return cls(**fakts.load_group(group))