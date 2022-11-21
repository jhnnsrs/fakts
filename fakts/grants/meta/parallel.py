from typing import List
from fakts.grants.base import FaktsGrant
import asyncio
from functools import reduce

from fakts.utils import update_nested


class ParallelGrant(FaktsGrant):
    """A grant that loads multiple grants in parallel and merges the results"""

    grants: List[FaktsGrant]
    omit_exceptions = False
    " Omit exceptions if any of the grants fail to load "

    async def aload(self, **kwargs):
        config_futures = [grant.aload(**kwargs) for grant in self.grants]
        configs = await asyncio.gather(
            config_futures, return_exceptions=self.omit_exceptions
        )
        return reduce(
            lambda x, y: update_nested(x, y) if isinstance(y, dict) else x, configs, {}
        )
