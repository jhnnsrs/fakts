from fakts_next.grants.errors import GrantError


class RemoteGrantError(GrantError):
    """Base class for all remotegrant errors"""

    pass


class DiscoveryError(RemoteGrantError):
    """An error that occurs when discovering the endpoint"""

    pass


class DemandError(RemoteGrantError):
    """An error that occurs while negotiating a session with the endpoint"""

    pass


class RetrieveError(DemandError):
    """An error that occurs when retrieving a token from the endpoint"""

    pass


class UserDeniedError(DemandError):
    """The user actively refused to grant the app access.

    First-class and catchable: a denial is a legitimate outcome of the
    device flow, not a malfunction, and an app should be able to exit
    quietly rather than treat it as a crash.
    """

    pass


class DeviceCodeExpiredError(DemandError):
    """The server expired the device code before the user approved it.

    Distinct from :class:`DeviceCodeTimeoutError`, which is the *client*
    giving up first.
    """

    pass


class DeviceCodeTimeoutError(DemandError):
    """The client's own deadline for the device flow elapsed."""

    pass


class DeviceCodeError(DemandError):
    """The device authorization endpoint refused the request."""

    pass
