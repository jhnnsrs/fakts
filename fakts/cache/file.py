import asyncio
import contextlib
import os
import stat
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

try:
    import grp
    import pwd
except ImportError:  # pragma: no cover - Windows
    grp = None  # type: ignore[assignment]
    pwd = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

LOCK_POLL_INTERVAL = 0.02
LOCK_TIMEOUT = 5.0
"""How long to wait for a sibling's cache transaction before giving up and
proceeding unlocked. A bounded wait is deliberate: the lock protects against
a lost rotation, but blocking forever on a stale lock file would be a worse
failure than the one it prevents."""


def ensure_private_dir(path: str) -> None:
    """Create ``path`` (and its parents) and make it private to this user.

    For whoever *creates* a directory that will hold a cache -- never from
    the read or write path. :meth:`FileCache.aload` must not narrow the
    directory it happens to find its cache in: ``cache_file`` defaults to a
    relative path, so that directory is routinely a project root or a source
    checkout, and silently turning someone's repo into ``0700`` is not this
    library's business.

    ``os.makedirs(path, mode=0o700)`` does not do this job, for two separate
    reasons that each look like it should:

    * the ``mode`` argument is masked by the umask, and the layout that
      caused this function to exist is precisely ``umask 002``; and
    * with ``exist_ok=True`` the mode is not applied at all to a directory
      that already exists -- which is the usual case, since the offending
      directory was created by an earlier version.

    Hence the unconditional ``chmod`` afterwards. A directory owned by
    someone else is left exactly as it is: we have no standing to narrow it,
    and :meth:`FileCache._warn_about_permissions` will say so at load time.
    """
    os.makedirs(path, exist_ok=True)

    if os.name != "posix":
        return

    try:
        info = os.stat(path)
        if info.st_uid != os.getuid():
            return
        if info.st_mode & 0o077:
            os.chmod(path, 0o700)
            logger.debug(
                "Tightened %s from %s to 0700.", path, oct(info.st_mode & 0o777)
            )
    except OSError:
        logger.debug("Could not make %s private.", path, exc_info=True)


def _describe_group(gid: int) -> str:
    """``"staff (alice, bob)"`` -- enough for the reader to check the claim."""
    if grp is None:
        return f"gid {gid}"
    try:
        entry = grp.getgrgid(gid)
    except KeyError:
        return f"gid {gid} (unresolvable)"
    if not entry.gr_mem:
        return entry.gr_name
    return f"{entry.gr_name} ({', '.join(sorted(entry.gr_mem))})"


def _group_may_contain_others(gid: int, owner_uid: int) -> bool:
    """Whether group ``gid`` plausibly contains someone other than the owner.

    This is the whole difference between a real finding and a false alarm.
    Debian and Ubuntu give every user a private group of their own and ship
    ``umask 002``, so a directory an app just created is ``0775`` with a
    group whose sole member is its owner. "Group-writable" there means
    "writable by the owner", and treating the bit alone as a finding warns on
    essentially every Linux desktop while detecting nothing.

    Two properties of ``gr_mem`` matter before changing this:

    * It lists *supplementary* members only. A user whose **primary** gid is
      this group never appears in it. That is exactly why the private-group
      case reads as empty -- the benign case we want silent.
    * So the converse does not hold: a shared project group that is several
      users' primary gid also reads as empty, and those users really can
      write. Closing that needs ``pwd.getpwall()``, which on an LDAP/SSSD box
      is slow to the point of hanging -- the very failure class this module
      is being fixed to stop causing. Do not add it.

    An unresolvable gid or uid is assumed shared. On a directory-service box
    it may name a real, populated group we simply cannot enumerate, and since
    nothing refuses on the answer any more, guessing loud costs one log line.
    """
    if grp is None or pwd is None:  # pragma: no cover - non-posix
        return True

    try:
        members = set(grp.getgrgid(gid).gr_mem)
        owner = pwd.getpwuid(owner_uid).pw_name
    except KeyError:
        return True

    return bool(members - {owner})



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
    differing hashes invalidate each other on every run). Pass an absolute
    path that identifies the app *and* the server to avoid both.

    ``arkitekt.app.fakts._cache_path`` is the worked example: one private
    per-user directory (via ``platformdirs``), with the app's identifier,
    its version and a hash of the server url in the filename. Create that
    directory with :func:`ensure_private_dir` -- the file is written 0600,
    but a bare ``os.makedirs`` leaves the directory at 0775 under the umask
    that most Linux distributions ship.


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

        self._warn_about_permissions(self.cache_file)
        self._ensure_private_file(self.cache_file)

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
    def _warn_about_permissions(path: str) -> None:
        """Report -- but never act on -- loose permissions on the cache.

        The cache is not merely a performance store: it names the token
        endpoint the client will POST its refresh token to, and the aliases
        it will send bearer tokens to. Anything that can write this file can
        redirect both. The manifest hash is no defence -- it is derived from
        public values.

        This used to *refuse* such a file, and that was wrong twice over.

        It was wrong about the common case. The predicate was
        ``st_mode & 0o022``, which catches the group bit, and under the
        user-private-group plus ``umask 002`` layout that Debian and Ubuntu
        ship, every directory an app creates is ``0775`` with a group whose
        only member is its owner. So it fired on essentially every Linux
        desktop while detecting nothing, and said "writable by other users"
        about a directory no other user could write. See
        :func:`_group_may_contain_others`.

        And refusing was not the safe branch. A refusal returns a cache miss,
        a miss re-runs the grant, and the grant opens a device-code prompt --
        which in a headless or scripted context is not a prompt, it is a
        hang. The "secure" path broke unattended clients over a condition
        that, on a normal desktop, was not a condition at all.

        So permissions no longer gate anything. What defends the credential
        is the discipline around it, all of it unchanged: the file is created
        ``0600`` before a byte is written (:meth:`aset`), read with
        ``O_NOFOLLOW``, replaced atomically, and restored to ``0600`` by
        :meth:`_ensure_private_file` if something loosened it. Those are
        mechanisms. A mode bit was only ever a report, so it is reported.

        Scope is deliberately the file and its immediate parent, not the
        ancestor chain. The controls above do not get stronger by walking
        further up, and what a walk would find -- bind mounts, container
        layouts, ``/home`` itself -- is mostly nothing the app can fix. On a
        normal desktop it would change no outcome anyway: the corrected
        predicate already passes the ``0775`` project directories it would
        surface.
        """
        if os.name != "posix":
            return

        try:
            uid = os.getuid()
            for target, kind, is_leaf in (
                (path, "file", True),
                (os.path.dirname(os.path.abspath(path)) or ".", "directory", False),
            ):
                # lstat on the leaf: a symlinked cache should be reported as a
                # symlink here, rather than surfacing later as the generic
                # "could not load" when the O_NOFOLLOW open returns ELOOP.
                info = os.lstat(target) if is_leaf else os.stat(target)
                mode = info.st_mode

                if is_leaf and stat.S_ISLNK(mode):
                    logger.warning(
                        "The fakts cache at %s is a symlink. It selects the endpoints "
                        "this app sends its refresh token to, so it is opened with "
                        "O_NOFOLLOW and this read will fail. Replace it with a real "
                        "file (rm %s) and re-authenticate.",
                        target,
                        target,
                    )
                    continue

                if info.st_uid != uid:
                    logger.warning(
                        "The fakts cache %s %s is owned by uid %s, not by this user "
                        "(uid %s). Whoever owns it chooses the endpoint this app POSTs "
                        "its refresh token to. Using it anyway; to be safe, remove it "
                        "(rm %s) and re-authenticate.",
                        kind,
                        target,
                        info.st_uid,
                        uid,
                        target,
                    )

                # The sticky bit only means "you may not replace another's
                # entries" on a directory; on a regular file it says nothing
                # about who may rewrite it. So /tmp is exempt, a 0666 file is not.
                sticky = bool(mode & stat.S_ISVTX) and not is_leaf

                if mode & 0o002 and not sticky:
                    logger.warning(
                        "The fakts cache %s %s is writable by any user on this machine "
                        "(mode %s), any of whom could redirect this app's refresh "
                        "token. Using it anyway; fix with: chmod o-w %s",
                        kind,
                        target,
                        oct(mode & 0o777),
                        target,
                    )

                if mode & 0o020:
                    if _group_may_contain_others(info.st_gid, info.st_uid):
                        logger.warning(
                            "The fakts cache %s %s is group-writable (mode %s) and its "
                            "group %s has members besides you, any of whom could "
                            "redirect this app's refresh token. Using it anyway; fix "
                            "with: chmod g-w %s",
                            kind,
                            target,
                            oct(mode & 0o777),
                            _describe_group(info.st_gid),
                            target,
                        )
                    else:
                        # The umask-002 case. Nobody else is in the group, so
                        # there is nothing to report -- this is the false alarm
                        # this function exists to have stopped emitting.
                        logger.debug(
                            "The fakts cache %s %s is group-writable (mode %s), but "
                            "group %s has no other members.",
                            kind,
                            target,
                            oct(mode & 0o777),
                            _describe_group(info.st_gid),
                        )
        except OSError:
            # Diagnostics only; it cannot deny anything, so a failed stat is
            # not worth a line in a working client's output.
            logger.debug("Could not check the cache file's permissions.", exc_info=True)

    @staticmethod
    def _ensure_private_file(path: str) -> None:
        """Restore ``0600`` on a cache we own but that something loosened.

        With :meth:`_warn_about_permissions` no longer gating, this is the
        strongest control left on an existing file -- so unlike a hygiene
        pass it deliberately heals the world-writable case too. There is no
        refusal left to preserve by declining to fix it.

        Must run *after* the diagnostic, never before: tightening a ``0666``
        file first would leave the diagnostic stat'ing ``0600``, the finding
        would vanish, and a world-writable cache would be adopted in silence.
        The two are ordered in :meth:`aload` for that reason.

        Goes through a file descriptor because ``os.chmod`` follows symlinks
        and Linux offers no ``follow_symlinks=False`` for it; chmod'ing by
        path would let a planted symlink retarget the mode change. Anything
        that goes wrong here -- a symlink, a file that vanished, a read-only
        mount -- is the diagnostic's business to describe, not this helper's
        to fix, so it never raises.
        """
        if os.name != "posix":
            return

        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(fd)
                if info.st_uid == os.getuid() and info.st_mode & 0o077:
                    os.fchmod(fd, 0o600)
                    logger.info(
                        "Tightened the fakts cache at %s from %s to 0600.",
                        path,
                        oct(info.st_mode & 0o777),
                    )
            finally:
                os.close(fd)
        except OSError:
            logger.debug("Could not tighten %s.", path, exc_info=True)

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
