class FaktsError(Exception):
    """Base class for all Fakts errors

    This class is used to catch all Fakts errors. If you want to catch
    all Fakts errors, you can catch this class.
    """


class NoFaktsFound(FaktsError):
    """Raised when no fakts_next instance is found in the current context.

    If this error is raised, it means that you are trying to access
    the fakts_next instance from a context where it is not available. Online
    places where it is available are:

    ```python

    with Fakts(grant=grant) as fakts_next:
        # fakts_next is available here

    async with Fakts(grant=grant) as fakts_next:
        # fakts_next is available here

    fake_fakts_next = Fakts(grant=grant)
    # fakt is not available here

    ```


    """


class NotEnteredError(FaktsError):
    """Raised when a Fakts method is called before entering the context

    Fakts needs to be used as a (async) context manager. This error is
    raised when a method that requires the context (locks, context
    variables) is called before `__aenter__` was run.
    """


class CompositionError(FaktsError):
    """Raised when required service instances could not be resolved

    This error is raised when one or more *required* services from the
    manifest could not be resolved to a working alias (no instance,
    no aliases, or all alias challenges failed).
    """


class AliasNotFoundError(FaktsError):
    """Raised when no alias could be resolved for a requested service key

    This error is raised when the alias for a service key could not be
    resolved, e.g. because the service is not part of the manifest
    requirements, or all of its alias challenges failed.

    The special case of a *declared* requirement that was simply not
    granted by the server raises the subclass
    :class:`ServiceNotGrantedError` instead, so callers of optional
    services can degrade gracefully.
    """


class ServiceNotGrantedError(AliasNotFoundError):
    """Raised when a declared service requirement was not granted

    The service key *is* declared in the manifest requirements, but the
    server did not grant an instance for it — e.g. the user declined
    access to an optional service, or the deployment does not offer it.

    This is a subclass of :class:`AliasNotFoundError`, so existing
    handlers keep working. Catch this error specifically to distinguish
    "the user did not grant this optional service" (expected, degrade
    gracefully) from "the key is unknown or the service is unreachable"
    (likely a bug or an infrastructure problem).
    """
