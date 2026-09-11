import asyncio
import contextlib
import os
import time
import uuid
from typing import AsyncIterator, Optional
import pydantic
import datetime
import logging
import json
from fakts.models import ActiveFakts

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

LOCK_POLL_INTERVAL = 0.02
LOCK_TIMEOUT = 5.0
"""How long to wait for a sibling's cache transaction before giving up and
proceeding unlocked. A bounded wait is deliberate: the lock protects against
a lost rotation, but blocking forever on a stale lock file would be a worse
failure than the one it prevents."""


class CacheFile(pydantic.BaseModel):
    """Cache file model"""

    fakts: ActiveFakts
    created: datetime.datetime
    hash: str = ""


class FileCache(pydantic.BaseModel):
    """Grant that caches the result of another grant

    This grant will cache the result of another grant in a file.
    It will load the grant on the first call, and then will load
    the cached version of the grant.

    Only if the cache is expired, or a "hash" value that is passed
    to the grant is different from the one in the cache, will it
    load the grant again.

    You can set the expires_in parameter to set the time in seconds
    for the cache to expire.

    Note that the default cache file path is *relative to the current
    working directory*: running the same app from a different directory
    will silently miss the cache (and re-run the grant), and two different
    apps run from the same directory will fight over the same file (their
    differing hashes invalidate each other on every run). Use an absolute,
    per-app cache path to avoid both.


    Attributes
    ----------
    grant : FaktsGrant
        The grant to cache
    cache_file : str
        The path to the cache file
    hash : str
        The hash to validate the cache against
    expires_in : Optional[int]
        The time in seconds for the cache to expire


    """

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    """The grant to cache"""

    cache_file: str = ".fakts_cache.json"
    """The path to the cache file"""
    hash: str = pydantic.Field(
        default_factory=lambda: "",
        description="Validating against the hash of the config",
    )
    """The hash to validate the cache against (if this value differes from the one in the cache, the grant will be reloaded)"""

    expires_in: Optional[int] = None
    """When should the cache expire"""

    async def aload(self) -> Optional[ActiveFakts]:
        """Loads the configuration from the grant

        It will try to load the configuration from the cache file.
        If the cache is expired, or the hash value is different from
        the one in the cache, it will load the grant again.

        Parameters
        ----------
        request : FaktsRequest
            The request object that may contain additional information needed for loading the configuration.

        Returns
        -------
        dict
            The configuration loaded from the grant.


        """

        if not os.path.exists(self.cache_file):
            return None

        if not self._is_trustworthy(self.cache_file):
            return None

        try:
            # O_NOFOLLOW: this file decides where the client sends its
            # credentials, so it must not be reachable through a symlink
            # someone else planted.
            fd = os.open(self.cache_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r") as f:
                x = json.load(f)
            cache = CacheFile(**x)
        except (json.JSONDecodeError, pydantic.ValidationError, OSError) as e:
            # A corrupt or unreadable cache should never break startup:
            # treat it as a cache miss and let the grant reload.
            #
            # Log only the shape of the failure. This file holds a refresh
            # token, and a pydantic ValidationError renders the offending
            # input — so logging `e` directly would emit part of the
            # credential on every start with a stale cache.
            if isinstance(e, pydantic.ValidationError):
                detail = "; ".join(
                    f"{'.'.join(str(p) for p in problem['loc']) or '<root>'}: {problem['type']}"
                    for problem in e.errors()
                )
            else:
                detail = type(e).__name__
            logger.error(
                "Could not load the fakts cache at %s (%s). Ignoring it.",
                self.cache_file,
                detail,
            )
            return None

        if self.hash and cache.hash != self.hash:
            return None

        if self.expires_in:
            if cache.created + datetime.timedelta(seconds=self.expires_in) < datetime.datetime.now():
                return None

        return cache.fakts

    @staticmethod
    def _is_trustworthy(path: str) -> bool:
        """Whether this file is safe to take configuration from.

        The cache is not merely a performance store: it names the token
        endpoint the client will POST its refresh token to, and the aliases
        it will send bearer tokens to. Anything that can write this file can
        redirect both. The manifest hash is no defence — it is derived from
        public values.

        So: refuse a file (or a containing directory) that someone else owns
        or that is group/other-writable. On Windows, where these bits do not
        mean the same thing, fall through and rely on the directory ACL.
        """
        if os.name != "posix":
            return True

        try:
            uid = os.getuid()
            for target, kind in (
                (path, "file"),
                (os.path.dirname(os.path.abspath(path)) or ".", "directory"),
            ):
                info = os.stat(target)
                if info.st_uid != uid:
                    logger.error(
                        "Refusing to read the fakts cache: %s %s is owned by uid %s, "
                        "not by this user. It selects the endpoints this app sends "
                        "its credentials to.",
                        kind,
                        target,
                        info.st_uid,
                    )
                    return False
                if info.st_mode & 0o022:
                    logger.error(
                        "Refusing to read the fakts cache: %s %s is writable by other "
                        "users (mode %s). It selects the endpoints this app sends its "
                        "credentials to.",
                        kind,
                        target,
                        oct(info.st_mode & 0o777),
                    )
                    return False
        except OSError:
            logger.warning("Could not check the cache file's ownership.", exc_info=True)
            return False

        return True

    @contextlib.asynccontextmanager
    async def atransaction(self) -> AsyncIterator[None]:
        """Hold an exclusive advisory lock for one read-compare-write.

        The file *write* is already atomic (temp file plus ``os.replace``), so
        no reader ever sees a torn cache. What was unprotected is the sequence
        around it: read the cache, decide our credential is not stale, write.
        An ``asyncio.Lock`` only orders that within one process, and a
        refresh-token cache is shared *between* processes by design — two
        siblings could each read the same state, each conclude they were safe,
        and the later rename would silently discard the other's rotation,
        leaving a revoked token on disk.

        The lock lives in a sibling ``.lock`` file rather than on the cache
        itself, because ``os.replace`` swaps the inode out from under any lock
        held on it.

        Acquired non-blockingly in a poll loop: ``flock`` blocks the whole
        thread, which in an event loop means every unrelated coroutine too.
        After :data:`LOCK_TIMEOUT` we proceed anyway — a stale lock file must
        degrade to the old behaviour, not wedge the client.
        """
        if fcntl is None:  # pragma: no cover - Windows
            # No flock; fall back to the previous single-process behaviour.
            yield
            return

        lock_path = f"{self.cache_file}.lock"
        fd: Optional[int] = None
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            logger.debug(
                "Could not open %s; proceeding without a cross-process lock.",
                lock_path,
                exc_info=True,
            )
            yield
            return

        acquired = False
        deadline = time.monotonic() + LOCK_TIMEOUT
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        logger.warning(
                            "Timed out waiting for the cache lock at %s; writing "
                            "without it. A concurrent rotation could be lost.",
                            lock_path,
                        )
                        break
                    await asyncio.sleep(LOCK_POLL_INTERVAL)
            yield
        finally:
            if acquired:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(fd)

    async def aset(self, value: ActiveFakts) -> None:
        """Refreshes the configuration from the grant

        This function is used to refresh the configuration from the grant.
        This is used to refresh the configuration from the grant, and should
        be used to refresh the configuration from the grant.

        The request object is used to pass information
        """

        cache = CacheFile(fakts=value, created=datetime.datetime.now(), hash=self.hash)

        # This file holds a live, rotating refresh token, so it is created
        # 0600 *before* anything is written to it. The mode has to be right
        # from the start: os.replace preserves the temp file's permissions,
        # which makes a chmod after the rename both too late and racy.
        # os.open's mode argument is masked by the umask, hence the fchmod.
        directory = os.path.dirname(os.path.abspath(self.cache_file)) or "."
        tmp_file = f"{self.cache_file}.{os.getpid()}.{uuid.uuid4().hex}.tmp"

        try:
            fd = os.open(tmp_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", closefd=False) as f:
                    f.write(cache.model_dump_json())
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                os.close(fd)

            await self._areplace_with_retry(tmp_file, self.cache_file)
        except Exception:
            # Never leave the secret lying around in a stray temp file.
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except OSError:
                pass
            raise

        # Without fsyncing the directory the rename itself can be lost on a
        # power failure, leaving the previous (now revoked) credential.
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Not every platform allows this; durability is best effort.
            logger.debug("Could not fsync %s after writing the cache.", directory)

    @staticmethod
    async def _areplace_with_retry(
        source: str, destination: str, attempts: int = 5
    ) -> None:
        """os.replace, tolerating a concurrent reader on Windows.

        POSIX renames over an open file happily; Windows raises
        PermissionError while another process has the destination open, so a
        sibling merely reading the cache would make our write fail.
        """
        for attempt in range(attempts):
            try:
                os.replace(source, destination)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                # asyncio.sleep, not time.sleep: this runs under
                # _load_lock inside the event loop, and blocking here
                # would stall every other coroutine in the process.
                await asyncio.sleep(0.05 * (attempt + 1))

    async def areset(self) -> None:
        """Delete the cached session.

        Runs inside :meth:`atransaction` like every other mutation: deleting
        is a write too, and doing it unlocked would race a sibling's rotation
        — the exact hazard the transaction exists to close. A sibling that
        rotates *after* this still re-persists a fresh credential, which is
        why :meth:`fakts.fakts.Fakts.alogout` cannot promise more than
        forgetting locally.

        The lock file itself is removed last, outside the lock it guards, so
        a logout does not leave litter next to a cache it just deleted.
        """
        lock_path = f"{self.cache_file}.lock"

        async with self.atransaction():
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)

        # Best effort: a sibling may legitimately hold the lock right now, in
        # which case it owns the file and will clean up after itself.
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except OSError:
            logger.debug("Could not remove %s.", lock_path, exc_info=True)
        return None
