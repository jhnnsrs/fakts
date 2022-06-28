from typing import List
from fakts.grants.base import FaktsGrant, GrantException
import asyncio
from functools import reduce
import logging
from fakts.utils import update_nested

logger = logging.getLogger(__name__)


class FailsafeGrant(FaktsGrant):
    grants: List[FaktsGrant]

    async def aload(self):
        for grant in self.grants:
            try:
                config = await grant.aload()
                return config
            except Exception:
                logger.exception(f"Failed to load {grant}", exc_info=True)
                continue

        raise GrantException("Failed to load any grants")
