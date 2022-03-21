from typing import List
from fakts.grants.base import FaktsGrant
from fakts.beacon import EndpointDiscovery, FaktsRetriever
import asyncio
from functools import reduce

from fakts.utils import update_nested


class ParallelGrant(FaktsGrant):
    parellized_grants: List[FaktsGrant]

    async def aload(self, previous={}, **kwargs):

        config_futures = [grant.aload(**kwargs) for grant in self.parellized_grants]
        configs = await asyncio.gather(config_futures)
        return reduce(lambda x, y: update_nested(x, y), configs, previous)
