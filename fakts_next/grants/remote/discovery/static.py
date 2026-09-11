from pydantic import BaseModel
from fakts_next.grants.remote.models import FaktsEndpoint


class StaticDiscovery(BaseModel):
    """A discovery that always returns the same endpoint

    This is mostly used for testing purposes.
    """

    endpoint: FaktsEndpoint

    async def adiscover(self) -> FaktsEndpoint:
        """Discover the endpoint

        This method will always return the same endpoint (the one that was
        passed to the constructor)

        Parameters
        ----------
        request : FaktsRequest
            The request to use for the discovery process (is not used)

        Returns
        -------
        FaktsEndpoint
            A valid endpoint
        """

        return self.endpoint
