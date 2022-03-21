from koil import koil
from pydantic import BaseModel


class MiddlewareException(Exception):
    pass


class FaktsMiddleware(BaseModel):
    async def aparse(self, previous={}, **kwargs):
        raise NotImplementedError()
