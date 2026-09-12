"""Cache backends for the granted configuration.

Under protocol v2 the cache holds a live, rotating refresh token, not just
configuration — see :mod:`fakts.cache.file` for the consequences.
"""

from .file import FileCache, ensure_private_dir
from .nocache import NoCache

__all__ = ["FileCache", "NoCache", "ensure_private_dir"]
