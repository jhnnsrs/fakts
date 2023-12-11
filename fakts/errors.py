class FaktsError(Exception):
    """Base class for all Fakts errors

    This class is used to catch all Fakts errors. If you want to catch
    all Fakts errors, you can catch this class.
    """


class NoFaktsFound(FaktsError):
    """Raised when no fakts instance is found in the current context.

    If this error is raised, it means that you are trying to access
    the fakts instance from a context where it is not available. Online
    places where it is available are:

    ```python

    with Fakts(grant=grant) as fakts:
        # fakts is available here

    async with Fakts(grant=grant) as fakts:
        # fakts is available here

    fake_fakts = Fakts(grant=grant)
    # fakt is not available here

    ```


    """


class GroupNotFound(FaktsError):
    """Raised when a group is not found in the configuration

    This error is raised when a group is not found in the configuration.
    This can happen when you try to access a group that does not exist
    in the active configuration. Also, this can be raised after a reload.




    """
