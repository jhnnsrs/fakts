from typing import Type, TypeVar
from pydantic import BaseSettings


Class = TypeVar("Class")


class ConfigError(Exception):
    pass


class Fakt(BaseSettings):
    class Config:
        extra = "ignore"

    @classmethod
    def new(cls: Type[Class], **kwargs: dict) -> Class:
        return cls(**kwargs)
