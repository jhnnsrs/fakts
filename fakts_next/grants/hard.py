from pydantic import BaseModel

from fakts_next.models import ActiveFakts


class HardFaktsGrant(BaseModel):
    """Hardcoded Fakts Grant"""

    fakts: ActiveFakts

    async def aload(self) -> ActiveFakts:
        """Loads the configuration from the hardcoded fakts"""
        return self.fakts
