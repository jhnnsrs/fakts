from typing import List, Dict
from fakts.grants.errors import GrantError
import logging
from fakts.types import FaktsRequest, FaktsGrant, FaktValue
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class FailsafeGrant(BaseModel):
    """
    Represent a Grant that loads configuration from a selection
    of other grants. It will try to load the grants in order,
    and will return the values from the first grant that succeeds.
    """

    grants: List[FaktsGrant]

    async def aload(self, request: FaktsRequest) -> Dict[str, FaktValue]:
        """Loads the configuration from the grant

        It will try to load the grants in order, and will return the values from the first grant that succeeds.


        Parameters
        ----------
        request : FaktsRequest
            The request object that may contain additional information needed for loading the configuration.

        Returns
        -------
        dict
            The configuration loaded from the grant.


        """
        for grant in self.grants:
            try:
                config = await grant.aload(request)
                return config
            except GrantError:
                logger.exception(f"Failed to load {grant}", exc_info=True)
                continue

        raise GrantError("Failed to load any grants")

    class Config:
        """A pydantic config class"""

        arbitrary_types_allowed = True
