from fakts.models import ActiveFakts
from fakts.protocols import FaktsCache


class NoCache(FaktsCache):
    """A cache implementation that does not store any data."""

    async def aload(self) -> ActiveFakts | None:
        """Always a miss: nothing is ever stored."""

        return None

    async def aset(self, value: ActiveFakts) -> None:
        """Discard ``value``."""

        pass

    async def areset(self) -> None:
        """Nothing to reset."""

        pass
