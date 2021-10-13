import asyncio

from pydantic.main import BaseModel
from konfik.grants import discover_konfik

class Nana(BaseModel):
    herre: dict


async def main():
    config = await discover_konfik(Nana)
    print(config)


asyncio.run(main())