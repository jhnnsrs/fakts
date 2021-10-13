from typing import Type, TypeVar
from pydantic import BaseSettings
from konfik.konfik import Konfik, get_current_konfik


Class = TypeVar("Class")

class Config(BaseSettings):

    class Config:
        extra = "ignore"
        group = "undefined"


    @classmethod
    def from_konfik(cls: Type[Class], konfik: Konfik = None, **overwrites) -> Class:
        group = cls.__config__.group
        assert group is not "undefined", f"Please overwrite the Metaclass Config parameter group and point at your group {cls}"
        konfik = konfik or get_current_konfik()
        return cls(**konfik.load_group(group))