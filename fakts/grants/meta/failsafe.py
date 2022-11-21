from typing import List
from fakts.grants.base import FaktsGrant
from fakts.grants.errors import GrantError
import logging

logger = logging.getLogger(__name__)


class FailsafeGrant(FaktsGrant):
    """A failsafe grant that tries to load a grant and if it fails it tries the next one. Only fails if all grants fail"""

    grants: List[FaktsGrant]

    async def aload(self, **kwargs):
        for grant in self.grants:
            try:
                config = await grant.aload(**kwargs)
                return config
            except GrantError as e:
                logger.exception(f"Failed to load {grant}", exc_info=True)
                continue

        raise GrantError("Failed to load any grants")
