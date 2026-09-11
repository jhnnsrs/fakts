from fakts_next.grants.errors import GrantError


class RemoteGrantError(GrantError):
    """Base class for all remotegrant errors"""

    pass


class ClaimError(RemoteGrantError):
    """An error that occurs when claiming the configuration from the endpoint"""

    pass


class DiscoveryError(RemoteGrantError):
    """An error that occurs when discovering the endpoint"""

    pass


class DemandError(RemoteGrantError):
    """An error that occurs when demanding the token from the endpoint"""

    pass
