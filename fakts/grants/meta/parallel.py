from typing import List
from fakts.grants.base import FaktsGrant
import asyncio
from functools import reduce

from fakts.utils import update_nested


class ParallelGrant(FaktsGrant):
    grants: List[FaktsGrant]

    async def aload(self):
        config_futures = [grant.aload() for grant in self.grants]
        configs = await asyncio.gather(config_futures)
        return reduce(lambda x, y: update_nested(x, y), configs, {})
