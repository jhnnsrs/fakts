from pydantic import BaseModel


class FaktsGrant(BaseModel):
    """Abstract Base Class for Fakts Grants

    Grants are used to load the configuration for Fakts. They are used to
    load configuration from a local file, a remote endpoint, a database, or
    any other source.

    A grant needs to implement the `aload` function, which is an
    async function. This means that it should not depend on cpu bound tasks.
    If you need to do cpu bound tasks, you should use a thread pool executor
    to do so.

    """

    async def aload(self, force_refresh=False):
        raise NotImplementedError("Fakts need to implement this function")
