class FaktsError(Exception):
    """Base class for all Fakts errors"""



class NoFaktsFound(FaktsError):
    """Raised when no fakts instance is found in the current context"""



class GroupNotFound(FaktsError):
    """Raised when a group is not found in the configuration"""

