"""Meta grant Module

In this module you can find all the grants that are used to combine multiple grants together.

"""


from .cache import CacheGrant
from .failsafe import FailsafeGrant
from .parallel import ParallelGrant

__all__ = ["CacheGrant", "FailsafeGrant", "ParallelGrant"]
