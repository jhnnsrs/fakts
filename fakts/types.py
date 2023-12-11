from pydantic import BaseModel
from typing import Dict, Any, Union, Protocol, runtime_checkable


NestedFaktValue = Union[str, int, float, bool, None, Dict[str, Any]]
FaktValue = Union[str, int, float, bool, None, Dict[str, NestedFaktValue]]


@runtime_checkable
class FaktsGrant(Protocol):
    """FaktsGrant

    A FaktsGrant is a grant that can be used to load configuration
    from a specific source. It can be used to load configuration
    from a file, from a remote endpoint, from a database, etc.
    """

    async def aload(self, request: "FaktsRequest") -> Dict[str, FaktValue]:
        """Loads the configuration from the grant

        Depending on the grant, this function may load the configuration
        from a file, from a remote endpoint, from a database, etc, the
        implementation of the grant will determine how the configuration
        is loaded.

        Generally, the grant should use preconfigured values to set the
        configuration retrievel logic, and should not use the request
        object to determine how to load the configuration.

        The request object is used to pass information between different
        grants, and should only be used to forward conditional information
        like "skip cache" or "force refresh". Which are mainly handled
        by meta grants.



        Parameters
        ----------
        request : FaktsRequest
            The request object that may contain additional information needed for loading the configuration.

        Returns
        -------
        dict
            The configuration loaded from the grant.

        Raises
        ------

        GrantError
            If the grant failed to load the configuration.+



        """
        ...


class FaktsRequest(BaseModel):
    """FaktsRequest

    A FaktsRequest is a request that is being processed by a
    Fakts grant. It contains the context of the request, which
    is a dictionary that can be used to store information between
    different steps of the grant.
    """

    is_refresh: bool = False
    """A flag that indicates whether the grant should refresh the configuration"""
    context: Dict[str, Any]
    """The context of the request"""
