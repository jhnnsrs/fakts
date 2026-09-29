"""What one Fakts shares between loading, tokens and aliases.

Concurrency invariants -- everything under fakts depends on these, so change
them only deliberately:

``L1``
    Lock order is strictly ``alias_lock -> token_lock -> load_lock``. Nothing
    reached while holding ``token_lock`` or ``load_lock`` may acquire
    ``alias_lock``.

``L2``
    :class:`asyncio.Lock` is not reentrant. Nothing reached from inside
    :meth:`fakts.session.TokenSession.afetch_token` may acquire ``token_lock``
    again -- in particular, never call a public token method from there.

``L3``
    Every cache write goes through :meth:`SessionState.apersist`, which
    refuses to overwrite a newer credential, checking and writing under
    ``load_lock``. Refresh tokens rotate, so a stale writer could otherwise
    clobber a live token with a revoked one. That orders sibling tasks, not
    sibling processes: two processes on one cache refreshing at the same
    instant can still lose a rotation, and the loser authenticates again.

    ``loaded_fakts`` is replaced under ``load_lock`` *or* ``token_lock`` (the
    token session reassigns it while renewing), never mutated in place.
    Readers re-read it after every await rather than holding a local across
    one -- a reload landing in between leaves the local pointing at a revoked
    credential.

``L4``
    A refresh-based grant needs a shared, persistent cache. Without one, every
    process holds its own credential and they revoke each other.

``L5``
    Alias state is written only under ``alias_lock``. Paths that cannot take
    it (L1) invalidate aliases by bumping ``instances_gen`` -- never by
    touching the resolver's maps.
"""

import asyncio
import logging
import time

from fakts.errors import FaktsError, NotEnteredError
from fakts.models import ActiveFakts, Manifest
from fakts.protocols import FaktsCache, FaktsGrant

logger = logging.getLogger(__name__)


class SessionState:
    """The loaded configuration, the token it holds, and the three locks.

    Outlives a single ``async with``: the configuration and token stay loaded
    across re-entry, while the locks belong to one entered block (they are
    bound to its event loop) and are replaced on every enter.
    """

    def __init__(
        self,
        *,
        manifest: Manifest,
        grant: FaktsGrant,
        cache: FaktsCache,
        allow_auto_load: bool,
    ) -> None:
        self.manifest = manifest
        self.grant = grant
        self.cache = cache
        self.allow_auto_load = allow_auto_load

        self.loaded_fakts: ActiveFakts | None = None
        self.loaded_token: str | None = None
        self.token_expires_at: float | None = None

        self.loaded_from_cache = False
        """Whether the *configuration* came from the cache rather than the
        grant. Only :meth:`aload` writes this. It gates the alias self-heal,
        which is a statement about how stale the instance list might be --
        adopting a sibling's credential says nothing about that."""
        self.credential_adopted = False
        """Whether we took over a credential another process rotated."""
        self.cache_write_failed = False

        self.instances_gen = 0
        """Bumped whenever the instances may have changed (a reload, an adopted
        or rotated credential). An alias refresh publishes itself as current
        only if this did not move while it ran (L5)."""

        self.alias_lock: asyncio.Lock | None = None
        self.token_lock: asyncio.Lock | None = None
        self.load_lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------ #
    # Entering                                                           #
    # ------------------------------------------------------------------ #

    @property
    def entered(self) -> bool:
        return self.load_lock is not None

    def enter(self) -> None:
        """Create the locks for one entered block."""
        self.alias_lock = asyncio.Lock()
        self.token_lock = asyncio.Lock()
        self.load_lock = asyncio.Lock()

    def exit(self) -> None:
        """Drop the locks: they belong to a loop that is going away."""
        self.alias_lock = None
        self.token_lock = None
        self.load_lock = None
        self.loaded_from_cache = False
        self.cache_write_failed = False

    def ensure_entered(self) -> None:
        if not self.entered:
            raise NotEnteredError(
                "You need to enter the Fakts context (`with`/`async with`) before "
                "calling this function"
            )

    # ------------------------------------------------------------------ #
    # Loading                                                            #
    # ------------------------------------------------------------------ #

    def grant_requires_interaction(self) -> bool:
        """Whether running the grant again would need a human."""
        return bool(getattr(self.grant, "requires_user_interaction", True))

    def invalidate_aliases(self) -> None:
        """The instances may have changed: resolved aliases are no longer current.

        Only the generation, never the resolver's maps -- this is reached from
        under token_lock and load_lock, which may not take alias_lock (L1).
        """
        self.instances_gen += 1

    async def aensure_loaded(self) -> ActiveFakts:
        """The loaded fakts, loading them first if allowed."""
        if self.loaded_fakts:
            return self.loaded_fakts
        if not self.allow_auto_load:
            raise FaktsError(
                "No fakts loaded and allow_auto_load is disabled. Please call load() "
                "explicitly first."
            )
        return await self.aload()

    async def aload(self, reload: bool = False) -> ActiveFakts:
        """Load the fakts from the cache or the grant; single-flight."""
        self.ensure_entered()
        assert self.load_lock is not None
        async with self.load_lock:
            if self.loaded_fakts and not reload:
                return self.loaded_fakts

            if not reload:
                cached_fakts = await self.cache.aload()
                if cached_fakts:
                    self.loaded_fakts = cached_fakts
                    self.loaded_from_cache = True
                    self.seed_token_from(cached_fakts)
                    return self.loaded_fakts

            self.loaded_fakts = await self.grant.aload()
            self.loaded_from_cache = False

            # The grant may have registered a brand new client: any
            # previously selected aliases and tokens are stale now.
            self.loaded_token = None
            self.token_expires_at = None
            self.invalidate_aliases()
            self.seed_token_from(self.loaded_fakts)

            # Persisting is best effort: the fakts are valid even if the
            # cache cannot be written (read-only directory, full disk, ...).
            # The grant just ran, so this credential supersedes whatever is
            # on disk even when nothing stamped it with an issue time.
            await self.apersist_locked(self.loaded_fakts, fresh_from_grant=True)
            return self.loaded_fakts

    def seed_token_from(self, fakts: ActiveFakts) -> None:
        """Reuse a still-valid access token that was persisted alongside.

        This is the single most effective defence against a refresh stampede:
        without it, every process starting up at once would immediately renew,
        and each renewal revokes the last. With it they share one access token
        for its full lifetime and simply do not contend.
        """
        access_token = fakts.auth.access_token
        if not access_token:
            return
        expires_at = fakts.auth.expires_at
        if expires_at is not None and time.time() >= expires_at:
            return
        self.loaded_token = access_token
        self.token_expires_at = expires_at

    async def areset(self) -> None:
        """Drop every trace of the session (callers hold the relevant locks)."""
        await self.cache.areset()
        self.loaded_fakts = None
        self.loaded_token = None
        self.token_expires_at = None
        self.loaded_from_cache = False
        self.credential_adopted = False
        self.invalidate_aliases()

    # ------------------------------------------------------------------ #
    # Persisting (L3)                                                    #
    # ------------------------------------------------------------------ #

    async def apersist(self, fakts: ActiveFakts) -> None:
        """Write fakts to the cache without clobbering a newer credential.

        Every cache write funnels through here (L3). The hazard it closes is
        not the obvious one: a process that never refreshed at all can still
        overwrite a sibling's freshly rotated token just by persisting the
        preferred alias order it happens to be holding.
        """
        assert self.load_lock is not None
        async with self.load_lock:
            await self.apersist_locked(fakts)

    async def apersist_locked(self, fakts: ActiveFakts, fresh_from_grant: bool = False) -> None:
        """As :meth:`apersist`, for callers already holding ``load_lock``.

        ``fresh_from_grant`` marks the one write that is allowed to replace a
        timed credential with an untimed one: the grant just ran and produced
        this, so it is newer than anything on disk by construction even though
        nothing stamped it. Every other caller has to prove it is not going
        backwards.
        """
        # The compare and the write are one step under load_lock, or a sibling
        # task's rotation lands between them and we overwrite it with a
        # credential the server has already revoked.
        try:
            existing = await self.cache.aload()
        except Exception:
            # Unknowable either way: skipping would lose a fresh rotation,
            # writing may replace a sibling's newer one. Write, but say so.
            logger.warning(
                "Could not read the fakts cache before writing it; writing without "
                "the stale-credential check.",
                exc_info=True,
            )
            existing = None

        if existing is not None and not fresh_from_grant and is_stale_auth(fakts, existing):
            logger.debug(
                "Skipping cache write: the cache holds a newer credential than "
                "the one we are about to persist."
            )
            return

        try:
            await self.cache.aset(fakts)
            self.cache_write_failed = False
        except Exception:
            if not self.cache_write_failed:
                self.cache_write_failed = True
                logger.error(
                    "Could not persist the fakts to the cache. If a refresh token "
                    "was just rotated, the credential on disk is now revoked and "
                    "the next start of this app will need to authenticate again.",
                    exc_info=True,
                )


def is_stale_auth(candidate: ActiveFakts, existing: ActiveFakts) -> bool:
    """Whether ``candidate`` would overwrite a newer credential.

    An absent ``refresh_issued_at`` means *unknown*, not "issued at the epoch".
    Coercing it to 0.0 made every freshly injected EnvGrant credential look
    older than whatever was already cached, so a re-provisioned container would
    refuse to persist its new token and then adopt the stale one back.

    But "unknown" must not mean "safe to write" either. Only
    :func:`fakts.oauth2.merge_token_response` ever stamps this field, so *every*
    credential straight from a grant carries ``None`` -- which turned the guard
    off in exactly the case it was written for. An untimed candidate therefore
    loses to a timed one; the caller that legitimately needs to install a fresh
    grant says so explicitly via ``fresh_from_grant``.
    """
    if candidate.auth.refresh_token == existing.auth.refresh_token:
        return False
    candidate_at = candidate.auth.refresh_issued_at
    existing_at = existing.auth.refresh_issued_at
    if existing_at is None:
        # Nothing to lose to: the cache itself is untimed.
        return False
    if candidate_at is None:
        # The cache holds a credential someone demonstrably rotated and we
        # cannot show ours is newer. Yield rather than revoke it.
        return True
    return candidate_at < existing_at
