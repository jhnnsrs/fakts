from pydantic import BaseModel

from fakts.models import ActiveFakts


class HardFaktsGrant(BaseModel):
    """Hardcoded Fakts Grant"""

    fakts: ActiveFakts

    requires_user_interaction: bool = False
    """Nothing to prompt for — the configuration is already in hand."""

    async def aload(self) -> ActiveFakts:
        """Loads the configuration from the hardcoded fakts.

        Returns a copy: :meth:`Fakts.arefresh_aliases` reorders each
        instance's alias list in place to remember the working route, and
        without the copy that would reach back into the caller's object.
        """
        return self.fakts.model_copy(deep=True)
