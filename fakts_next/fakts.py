"""The Fakts client: configuration, alias resolution and OAuth2 tokens.

Concurrency invariants — the whole file depends on these, so change them
only deliberately:

``L1``
    Lock order is strictly ``_alias_lock -> _token_lock -> _load_lock``.
    Nothing reached while holding ``_token_lock`` or ``_load_lock`` may
    acquire ``_alias_lock``.

``L2``
    :class:`asyncio.Lock` is not reentrant. Nothing reached from inside
    :meth:`Fakts._afetch_token` may acquire ``_token_lock`` again — in
    particular, never call :meth:`Fakts.aget_token` from there.

``L3``
    Every cache write goes through :meth:`Fakts._apersist`, which refuses to
    overwrite a newer credential — and does the check and the write inside
    the cache's own transaction, so the pair is atomic against sibling
    *processes* too, not just sibling tasks. Refresh tokens rotate, so a
    stale writer can otherwise clobber a live token with a revoked one.

    ``loaded_fakts`` is mutated under ``_load_lock`` *or* ``_token_lock``
    (:meth:`_acommit_token_response` and :meth:`_aadopt_cached_credentials`
    reassign it while renewing). Readers must therefore re-read it after
    every await rather than holding a local across one — a reload landing in
    between leaves the local pointing at a revoked credential.

``L4``
    A refresh-based grant needs a shared, persistent cache. Without one,
    every process holds its own credential and they revoke each other. The
    cache must implement ``atransaction`` for L3's cross-process half to
    hold; :class:`~fakts_next.cache.file.FileCache` does.

``L5``
    Alias state (``alias_map``, ``report_map``, ``_aliases_refreshed``,
    ``_unchallenged_keys``) is written only under ``_alias_lock`` — the
    public :meth:`Fakts.arefresh_aliases` takes it, and everything already
    holding it calls :meth:`Fakts._arefresh_aliases_locked` instead. The one
    exception is invalidation from the token path, which may only *clear*
    ``_aliases_refreshed`` (never touch the maps), because L1 puts
    ``_alias_lock`` out of reach from there.
"""

import asyncio
import contextlib
import contextvars
import logging
import random
import ssl
import time
from enum import Enum
from ssl import SSLContext
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Set, Tuple, Type

import aiohttp
import certifi
from pydantic import BaseModel, Field

from fakts_next import oauth2
from fakts_next.cache.nocache import NoCache
from fakts_next.errors import (
    AliasNotFoundError,
    CompositionError,
    FaktsError,
    NoFaktsFound,
    NotEnteredError,
    NeedsReauthenticationError,
    ServiceNotGrantedError,
)
from koil.composition import KoiledModel
from koil.bridge import unkoil

from .challenge import generate_nonce, verify_challenge_signature
from .models import (
    ActiveFakts,
    Alias,
    AuthFakt,
    ChallengeKey,
    GrantStatus,
    Manifest,
    Requirement,
)
from .protocols import FaktsCache, FaktsGrant
from .utils import truncate

logger = logging.getLogger(__name__)
current_fakts_next: contextvars.ContextVar[Optional["Fakts"]] = contextvars.ContextVar(
    "current_fakts_next", default=None
)

TOKEN_EXPIRY_SKEW = oauth2.TOKEN_EXPIRY_SKEW
"""Seconds before the actual expiry at which a token is considered expired.

Re-exported from :mod:`fakts_next.oauth2`, which owns the value."""

REPORT_TIMEOUT = 5
"""Seconds to allow the alias report. Deliberately short and separate: the
report runs while ``_alias_lock`` is held, so a slow endpoint would otherwise
stall every alias lookup in the process. Telemetry must never be able to do
that."""

REFRESH_TOKEN_MAX_AGE = 30 * 24 * 3600
"""How long a single refresh token is assumed to stay usable. Servers
enforce their own value; this is only used to fail fast with a truthful
message instead of a doomed round trip."""

REFRESH_CHAIN_MAX_AGE = 180 * 24 * 3600
"""How long a refresh *chain* may keep being renewed before the
authorization has to be granted afresh. Rotating does not reset it, which
is why even a permanently running app eventually needs a human."""

REFRESH_RETRY_DELAY = 0.25
REFRESH_RETRY_ROUNDS = 4
MAX_ADOPTIONS = 4
"""How many distinct credentials one renewal will try before giving up.
Bounded by the set of credentials actually seen, so it cannot spin."""

_REAUTH_REASONS = {
    "idle": "This app's authorization has been unused for too long.",
    "chain_expired": "This app's authorization has reached its maximum age.",
    "superseded": "This app's registration was replaced, most likely by a fresh approval elsewhere.",
    "rejected": "The server rejected this app's stored credential.",
    "exhausted": "None of the stored credentials were accepted.",
}


def _same_origin(left: str, right: str) -> bool:
    """Whether two URLs share scheme, host and port."""
    a, b = urlparse(left), urlparse(right)
    return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)


class ReauthPolicy(str, Enum):
    """When the token path may run an interactive grant on its own.

    A single boolean cannot express this, because the same client is used
    from places with very different tolerances: a 401 inside a GraphQL
    request must never open a browser, while a user typing ``fakts.load()``
    at a REPL reasonably expects one.
    """

    NEVER = "never"
    """Always raise :class:`NeedsReauthenticationError` instead of prompting."""

    ON_EXPLICIT_LOAD = "on_explicit_load"
    """The default. Only an explicit load or refresh may prompt; automatic
    token renewal never does."""

    ALWAYS = "always"
    """Legacy behaviour: let any token renewal prompt. Convenient for
    single-process interactive apps, hazardous anywhere else."""


class AliasReport(BaseModel):
    alias_id: str | None = None
    reason: str | None = None
    valid: bool = False


class ReportRequest(BaseModel):
    alias_reports: Dict[str, AliasReport]
    functional: bool


class Fakts(KoiledModel):
    """The asynchronous configuration and service-discovery client.

    Fakts loads the active configuration (:class:`ActiveFakts`) of an app
    through a *grant* — typically the remote protocol against a Fakts
    server, but also hardcoded values or environment variables — caches
    it, resolves the services required by the app's :class:`Manifest` to
    working aliases, and hands out OAuth2 tokens.

    Use it as a context manager. All methods come in an async variant
    (``a``-prefixed) and a sync variant (via koil), so the same instance
    works in scripts, notebooks and async applications.

    Example:
        ```python
        from fakts_next import build_device_code_fakts, Manifest, Requirement

        fakts = build_device_code_fakts(
            url="http://localhost:8000",
            manifest=Manifest(
                identifier="my-app",
                version="0.1.0",
                scopes=["openid"],
                requirements=[
                    Requirement(key="rekuest", service="live.arkitekt.rekuest"),
                ],
            ),
        )

        async with fakts:
            alias = await fakts.aget_alias("rekuest")  # resolved, challenged service address
            url = alias.to_http_path("graphql")
            token = await fakts.aget_token()           # OAuth2 access token
        ```

    Loading is single-flight and cached: the grant runs at most once per
    process (concurrent callers share the load), and with a configured
    cache it does not run again across restarts until the cache is
    invalidated (e.g. by a changed manifest). Alias resolution challenges
    every requirement once and then sticks to the last working alias.

    Entering the context also sets the current fakts context variable, so
    `get_current_fakts_next()` (and the `fakt`/`afakt` helpers) work from
    anywhere in your code.
    """

    cache: FaktsCache = Field(default_factory=NoCache, exclude=True)

    """" Requirmements """
    manifest: Manifest

    """"The manifest of the fakts. This is used to describe the fakts and its capabilities."""
    ssl_context: SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where())
    )

    grant: FaktsGrant
    """The grant to load the configuration from"""

    loaded_fakts: ActiveFakts | None = Field(default=None, exclude=True)
    """The currently loaded fakts. Please use `get` to access the fakts"""

    alias_map: Dict[str, Alias] = Field(
        default_factory=dict,
        exclude=True,
        description="Map of service names to active aliases",
    )
    report_map: Dict[str, AliasReport] = Field(
        default_factory=dict,
        exclude=True,
        description="Map of service names to the outcome of their alias challenges",
    )

    loaded_token: Optional[str] = Field(
        default=None, exclude=True, description="The currently loaded token"
    )

    allow_auto_load: bool = Field(
        default=True, description="Should we autoload on get?"
    )
    """Should we autoload the grants on a call to get?"""

    delete_on_exit: bool = False
    """Should we reset the cache (and loaded state) when exiting the context?"""

    refetch_on_alias_failure: bool = True
    """If resolving required aliases from *cached* fakts fails, should we reload
    the fakts from the grant and retry once? This self-heals stale caches
    (e.g. when services moved since the fakts were cached)."""

    alias_challenge_timeout: float = 3
    """Timeout (in seconds) for a single alias challenge request"""

    reauth_policy: ReauthPolicy = ReauthPolicy.ON_EXPLICIT_LOAD
    """When automatic token renewal is allowed to fall back to running the
    grant interactively. The default keeps browsers out of the token path;
    see :class:`ReauthPolicy`."""

    allow_insecure_transport: bool = False
    """Permit sending OAuth2 credentials over plain HTTP to a non-loopback
    host. Fakts supports plain-HTTP deployments on a network, but since v2
    puts a rotating refresh token on the wire it has to be chosen, not
    stumbled into. Loopback never needs this."""

    _load_lock: Optional[asyncio.Lock] = None
    _token_lock: Optional[asyncio.Lock] = None
    _alias_lock: Optional[asyncio.Lock] = None
    _token_expires_at: Optional[float] = None
    _loaded_from_cache: bool = False
    """Whether the *configuration* came from the cache rather than the grant.

    Only :meth:`aload` writes this. It gates the alias self-heal, which is a
    statement about how stale the instance list might be — adopting a
    sibling's credential says nothing about that, so it must not flip this
    (see ``_credential_adopted``)."""
    _credential_adopted: bool = False
    """Whether we took over a credential another process rotated. Diagnostic
    only; kept separate so it cannot be mistaken for a stale instance list."""
    _aliases_refreshed: bool = False
    _unchallenged_keys: set = set()
    """Keys whose cached alias was accepted without probing it.

    ``omit_challenge=True`` stores an alias nobody verified. Serving that
    back to a later caller who *did* want a challenge would silently skip
    the probe — and, where the instance pins a key, the signature check with
    it — for the rest of the process."""
    _cache_write_failed: bool = False
    _context_token: Optional[Any] = None

    def _ensure_entered(self) -> None:
        """Raise if the context manager was not entered yet"""
        if (
            self._load_lock is None
            or self._token_lock is None
            or self._alias_lock is None
        ):
            raise NotEnteredError(
                "You need to enter the Fakts context (`with`/`async with`) before calling this function"
            )

    async def _aensure_loaded(self) -> ActiveFakts:
        """Return the loaded fakts, auto-loading them if allowed"""
        if self.loaded_fakts:
            return self.loaded_fakts
        if not self.allow_auto_load:
            raise FaktsError(
                "No fakts loaded and allow_auto_load is disabled. Please call load() explicitly first."
            )
        return await self.aload()

    async def aload(self, reload: bool = False) -> ActiveFakts:
        """Load the fakts from the cache or the grant (async)

        This method is single-flight: concurrent callers share one load, so
        an interactive grant (e.g. the device code flow) can never be
        triggered twice in parallel. If the fakts are already loaded, they
        are returned as-is unless ``reload`` is set.

        Args:
            reload (bool, optional): Bypass the loaded fakts and the cache,
                and load freshly from the grant. Defaults to False.

        Returns:
            ActiveFakts: The loaded fakts
        """
        self._ensure_entered()
        assert self._load_lock is not None
        async with self._load_lock:
            if self.loaded_fakts and not reload:
                return self.loaded_fakts

            if not reload:
                cached_fakts = await self.cache.aload()
                if cached_fakts:
                    self.loaded_fakts = cached_fakts
                    self._loaded_from_cache = True
                    self._seed_token_from(cached_fakts)
                    return self.loaded_fakts

            self.loaded_fakts = await self.grant.aload()
            self._loaded_from_cache = False

            # The grant may have registered a brand new client: any
            # previously selected aliases and tokens are stale now.
            self.loaded_token = None
            self._token_expires_at = None
            self.alias_map = {}
            self.report_map = {}
            self._aliases_refreshed = False
            self._seed_token_from(self.loaded_fakts)

            # Persisting is best effort: the fakts are valid even if the
            # cache cannot be written (read-only directory, full disk, ...).
            # The grant just ran, so this credential supersedes whatever is
            # on disk even when nothing stamped it with an issue time.
            await self._apersist_locked(self.loaded_fakts, fresh_from_grant=True)
            return self.loaded_fakts

    def _seed_token_from(self, fakts: ActiveFakts) -> None:
        """Reuse a still-valid access token that was persisted alongside.

        This is the single most effective defence against a refresh
        stampede: without it, every process starting up at once would
        immediately renew, and each renewal revokes the last. With it they
        share one access token for its full lifetime and simply do not
        contend.
        """
        access_token = fakts.auth.access_token
        if not access_token:
            return
        expires_at = fakts.auth.expires_at
        if expires_at is not None and time.time() >= expires_at:
            return
        self.loaded_token = access_token
        self._token_expires_at = expires_at

    async def alogin(self) -> ActiveFakts:
        """Ensure this app has a working session, prompting only if it must.

        This is the recovery :class:`NeedsReauthenticationError` points at,
        and the thing to call at startup when a prompt is acceptable. It is
        idempotent: a healthy session returns immediately, without a prompt
        and without rotating anything.

        That is the whole difference from :meth:`arefresh`, which *always*
        re-runs the grant — and re-running an interactive grant makes the
        server replace this app's client registration, severing every other
        process sharing the credential. So reach for this one by default and
        for :meth:`arefresh` only when you specifically mean "start over".

        ```python
        try:
            token = await fakts.aget_token()
        except NeedsReauthenticationError:
            await fakts.alogin()
            token = await fakts.aget_token()
        ```
        """
        self._ensure_entered()
        fakts = await self._aensure_loaded()
        # interactive=True is what separates this from an ordinary token
        # fetch: here a browser opening is the point, not an ambush.
        await self.aget_token(interactive=True)
        return self.loaded_fakts or fakts

    async def alogout(self) -> None:
        """Forget this app's session on this machine.

        **This does not revoke anything.** The fakts protocol defines no
        revocation endpoint, so the refresh token stays valid server-side
        until it expires on its own. Anyone holding a copy can still use it.

        It is also not, by itself, a logout for the *machine*. Sibling
        processes keep the credential they already hold in memory, and the
        first one to rotate writes a fresh, still-valid credential straight
        back into the cache — the persist path has no notion of "this was
        deliberately cleared". Treat this as "forget here and now": correct
        for a single-process app, and for scripts prefer ``delete_on_exit``.

        A subsequent call that needs configuration re-runs the grant, which
        for an interactive grant means prompting again.
        """
        self._ensure_entered()
        assert self._alias_lock is not None
        assert self._token_lock is not None
        assert self._load_lock is not None
        # Logout is the one operation that legitimately touches all three
        # state domains, so it takes all three locks — in L1 order.
        async with self._alias_lock:
            async with self._token_lock:
                async with self._load_lock:
                    await self._alogout_locked()

    async def _alogout_locked(self) -> None:
        """Drop every trace of the session. Callers hold the relevant locks.

        Shared with ``delete_on_exit`` so the two cannot drift: this used to
        be inlined in :meth:`__aexit__`, where it ran under no lock at all.
        """
        await self.cache.areset()
        self.loaded_fakts = None
        self.loaded_token = None
        self._token_expires_at = None
        self.alias_map = {}
        self.report_map = {}
        self._aliases_refreshed = False
        self._unchallenged_keys = set()
        self._loaded_from_cache = False
        self._credential_adopted = False

    async def arefresh(self) -> ActiveFakts:
        """Refresh the fakts (async)

        Reloads the fakts from the grant (bypassing the cache) and updates
        the cache with the result.

        This *always* re-runs the grant, which for an interactive one
        replaces the app's client registration and disconnects every sibling
        process. To recover a session, prefer :meth:`alogin`, which prompts
        only when it has to.
        """
        return await self.aload(reload=True)

    async def _afetch_token(self, interactive: bool = False) -> str:
        """Renew the access token using the refresh grant.

        Must be called while holding ``_token_lock`` (L2: nothing here may
        take it again).

        The awkward part is not the HTTP call, it is that refresh tokens
        rotate: every use revokes its predecessor, and sibling processes
        share one cache file. Three cheap measures keep that from turning
        into a stampede, in order of how much they buy:

        1. *Read before refreshing.* Our in-memory token may have been
           rotated away by a sibling hours ago; noticing costs one file read
           and saves a guaranteed-doomed round trip.
        2. *Adopt by untried credential, not by retry count.* A herd of
           processes starting on the same token converges one per round, so
           a fixed "retry once" strands most of them. Looping while the
           cache still offers something we have not tried is self-limiting
           and actually converges.
        3. *Escalate on content, never on a timer.* Giving up because a
           sibling's write had not landed yet would re-run the grant, which
           deletes that sibling's client — a millisecond of bad luck
           cascading into an outage for everyone.
        """
        # Note on "never interactive": that contract governs *re*-authentication
        # (see _areauthenticate), not the first load. When nothing is loaded
        # yet, _aensure_loaded() below runs the grant — which for a device-code
        # grant can prompt. That is `allow_auto_load`'s decision to make, not
        # this method's, so set allow_auto_load=False if a 401 must never be
        # able to trigger an initial grant.
        fakts = await self._aensure_loaded()

        # (1) our credential may already be stale.
        adopted = await self._aadopt_cached_credentials(set())
        if adopted is not None:
            fakts = adopted
            # The adopted entry may carry an access token that is still good.
            # Spending a rotation on top of it would be pure loss.
            if self._token_is_valid() and self.loaded_token:
                return self.loaded_token

        tried: Set[Tuple[str, str]] = set()
        # What we came in holding. Every await below can yield to a concurrent
        # aload(reload=True), which replaces loaded_fakts wholesale; comparing
        # against this is how we notice that happened.
        entry_token = self.loaded_token

        for _ in range(MAX_ADOPTIONS):
            # Re-read rather than trusting the local. A reload that landed
            # while we were blocked leaves `fakts` pointing at a credential
            # the server has already revoked — and _aadopt_cached_credentials
            # will not rescue us, because the cache now matches loaded_fakts
            # and it correctly reports "nothing new". We would then spend
            # every round posting a dead token and end up demanding a
            # reauthentication that nothing actually required.
            fakts = self.loaded_fakts or fakts

            # Deliberately "did it change", never "is it valid": arefresh_token
            # gets here precisely when loaded_token is the token the server
            # just rejected, and a rejected token is usually not expired.
            if (
                self.loaded_token is not None
                and self.loaded_token != entry_token
                and self._token_is_valid()
            ):
                return self.loaded_token

            auth = fakts.auth

            # Cheap local check before spending a round trip, and it yields
            # a truthful message instead of a guess at what went wrong.
            expiry_reason = self._classify_refresh_expiry(auth)
            if expiry_reason:
                return await self._areauthenticate(
                    reason=expiry_reason, interactive=interactive
                )

            tried.add((auth.client_id, auth.refresh_token))

            try:
                data = await oauth2.apost_form(
                    auth.token_endpoint,
                    {
                        "grant_type": oauth2.REFRESH_GRANT,
                        "refresh_token": auth.refresh_token,
                        "client_id": auth.client_id,
                    },
                    ssl_context=self.ssl_context,
                    allow_insecure_transport=self.allow_insecure_transport,
                )
            except oauth2.OAuth2ErrorResponse as e:
                if e.error not in ("invalid_grant", "invalid_client"):
                    raise FaktsError(
                        f"The token endpoint {auth.token_endpoint} refused to renew "
                        f"the session for client '{auth.client_id}': {e}"
                    ) from e

                logger.debug(
                    "Refresh rejected (%s); looking for a credential another "
                    "process may have written.",
                    e.error,
                )
                adopted = await self._aawait_untried_credentials(tried)
                if adopted is None:
                    return await self._areauthenticate(
                        reason=(
                            "superseded"
                            if e.error == "invalid_client"
                            else "rejected"
                        ),
                        interactive=interactive,
                    )
                fakts = adopted
                # The credential we just adopted may already carry a usable
                # access token — the sibling that rotated ahead of us got one.
                # Rotating again on top of it would revoke the very token we
                # adopted and push the sibling into the same recovery, which
                # is how a stampede sustains itself.
                if self._token_is_valid() and self.loaded_token:
                    return self.loaded_token
                continue
            except FaktsError:
                raise
            except Exception as e:
                raise FaktsError(
                    f"Could not reach the token endpoint {auth.token_endpoint} to "
                    f"renew the session: {e}"
                ) from e

            return await self._acommit_token_response(fakts, data)

        return await self._areauthenticate(
            reason="exhausted", interactive=interactive
        )

    async def _acommit_token_response(
        self, previous: ActiveFakts, data: Dict[str, Any]
    ) -> str:
        """Persist a rotated credential, *then* start using it.

        The order matters and is not merely tidy. The server commits the
        rotation when it answers, so from that instant the old refresh token
        is dead. If we adopted the new one in memory and only then failed to
        write it, this process would keep working while the credential on
        disk stayed revoked — a breakage that surfaces at the next restart,
        far from its cause.
        """
        response = oauth2.TokenResponse(**data)
        candidate = oauth2.merge_token_response(
            previous,
            response,
            token_endpoint=previous.auth.token_endpoint,
            report_endpoint=previous.auth.report_endpoint,
            skew=TOKEN_EXPIRY_SKEW,
            fallback_client_id=previous.auth.client_id,
        )

        await self._apersist(candidate)

        aliases_changed = oauth2.instances_changed(previous, candidate)

        self.loaded_fakts = candidate
        self.loaded_token = candidate.auth.access_token
        self._token_expires_at = candidate.auth.expires_at

        if aliases_changed:
            # Only flag it: clearing alias_map here would race with a
            # resolution in flight, and L1 forbids taking _alias_lock from
            # under _token_lock.
            self._aliases_refreshed = False

        if not self.loaded_token:
            raise FaktsError(
                f"The token endpoint {candidate.auth.token_endpoint} answered "
                f"without an access_token."
            )
        return self.loaded_token

    def _classify_refresh_expiry(self, auth: AuthFakt) -> Optional[str]:
        """Name a locally-detectable expiry, if there is one.

        Servers enforce two independent limits: how long one refresh token
        stays usable, and how long a chain may keep being renewed. Both are
        computable from what we persisted, so we can fail with a true
        explanation instead of asking and then guessing at ``invalid_grant``.
        """
        now = time.time()
        if (
            auth.refresh_issued_at
            and now - auth.refresh_issued_at > REFRESH_TOKEN_MAX_AGE
        ):
            return "idle"
        if (
            auth.chain_started_at
            and now - auth.chain_started_at > REFRESH_CHAIN_MAX_AGE
        ):
            return "chain_expired"
        return None

    async def _aawait_untried_credentials(
        self, tried: Set[Tuple[str, str]]
    ) -> Optional[ActiveFakts]:
        """Wait briefly for a sibling's rotation to land, then adopt it.

        Terminates for the right reason: we only ever accept a credential we
        have not already tried, so this cannot spin. The sleep is jittered so
        that N processes racing on the same file do not re-read in lockstep.
        """
        for round_index in range(REFRESH_RETRY_ROUNDS):
            adopted = await self._aadopt_cached_credentials(tried)
            if adopted is not None:
                return adopted
            if round_index == REFRESH_RETRY_ROUNDS - 1:
                # Nothing re-reads the cache after this, so sleeping here only
                # holds _token_lock — and every other token consumer in the
                # process with it — for nothing.
                break
            await asyncio.sleep(REFRESH_RETRY_DELAY * (1 + random.random()))
        return None

    async def _aadopt_cached_credentials(
        self, tried: Set[Tuple[str, str]]
    ) -> Optional[ActiveFakts]:
        """Adopt the cached credential if it is one we have not tried.

        The key is the whole ``(client_id, refresh_token)`` pair, not the
        token alone: re-approval rotates the client identity too, and a
        refresh token is only ever valid for the client it was issued to.

        Must be called while holding ``_token_lock``; takes ``_load_lock``
        (L1: token before load).
        """
        assert self._load_lock is not None
        async with self._load_lock:
            try:
                cached = await self.cache.aload()
            except Exception:
                logger.warning(
                    "Could not re-read the cache while renewing the session.",
                    exc_info=True,
                )
                return None

            if not cached:
                return None

            key = (cached.auth.client_id, cached.auth.refresh_token)
            if key in tried:
                return None

            current = self.loaded_fakts
            if current is not None and key == (
                current.auth.client_id,
                current.auth.refresh_token,
            ):
                return None

            logger.info(
                "Adopting the credential another process wrote to the cache "
                "instead of renewing our own."
            )
            # Adopting replaces the whole ActiveFakts, instances included, so
            # any alias resolved against the old ones may now point at a
            # service this credential does not reach. Under multi-process load
            # this is the *common* path, not an edge case — invalidating only
            # in _acommit_token_response would miss it every time.
            #
            # Flag only: L1 forbids taking _alias_lock from under _token_lock,
            # and clearing alias_map here would race a resolution in flight.
            if current is not None and oauth2.instances_changed(current, cached):
                self._aliases_refreshed = False
            self.loaded_fakts = cached
            self._credential_adopted = True
            # Keep the access token that came with it. Discarding it and
            # rotating anyway is the stampede this whole read-before-refresh
            # step exists to avoid: we would revoke the very credential we
            # just adopted, forcing the process we adopted it from to adopt
            # in turn, and so on around the ring.
            self.loaded_token = None
            self._token_expires_at = None
            self._seed_token_from(cached)
            return cached

    async def _areauthenticate(self, *, reason: str, interactive: bool) -> str:
        """Last resort: re-run the grant, but only when that is safe.

        Re-running an *interactive* grant is not a quiet retry. It opens a
        browser and makes the server mint a replacement client, deleting the
        old one — which severs every sibling process sharing this cache. So
        it happens only when a human actually asked for it.

        Non-interactive grants (redeem, a supplied credential) carry no such
        cost, which is what keeps headless deployments recoverable.
        """
        explanation = _REAUTH_REASONS.get(reason, "The session could not be renewed.")

        if not self._grant_requires_interaction():
            logger.info("Re-running the non-interactive grant: %s", explanation)
            await self.aload(reload=True)
            return await self._afetch_after_reload()

        if interactive and self.reauth_policy is not ReauthPolicy.NEVER:
            logger.info("Re-running the interactive grant: %s", explanation)
            await self.aload(reload=True)
            return await self._afetch_after_reload()

        raise NeedsReauthenticationError(
            f"{explanation} This app must be authorized again, which needs "
            f"someone at a browser. Call fakts.alogin() when prompting is "
            f"appropriate, or set reauth_policy=ReauthPolicy.ALWAYS to let the "
            f"token path prompt on its own."
        )

    async def _afetch_after_reload(self) -> str:
        """Return the token the freshly reloaded grant produced."""
        fakts = await self._aensure_loaded()
        if fakts.auth.access_token:
            self.loaded_token = fakts.auth.access_token
            self._token_expires_at = fakts.auth.expires_at
            return fakts.auth.access_token
        raise FaktsError(
            "The grant completed but produced no access token."
        )

    def _grant_requires_interaction(self) -> bool:
        """Whether reloading the grant would need a human."""
        return bool(getattr(self.grant, "requires_user_interaction", True))

    async def _apersist(self, fakts: ActiveFakts) -> None:
        """Write fakts to the cache without clobbering a newer credential.

        Every cache write funnels through here (L3). The hazard it closes is
        not the obvious one: a process that never refreshed at all can still
        overwrite a sibling's freshly rotated token just by persisting the
        preferred alias order it happens to be holding. That leaves a
        revoked credential on disk and breaks everyone.
        """
        assert self._load_lock is not None
        async with self._load_lock:
            await self._apersist_locked(fakts)

    async def _apersist_locked(
        self, fakts: ActiveFakts, fresh_from_grant: bool = False
    ) -> None:
        """As :meth:`_apersist`, for callers already holding ``_load_lock``.

        ``fresh_from_grant`` marks the one write that is allowed to replace a
        timed credential with an untimed one: the grant just ran and produced
        this, so it is newer than anything on disk by construction even though
        nothing stamped it. Every other caller has to prove it is not going
        backwards.
        """
        # _load_lock orders this within the process; the cache's own
        # transaction (when it has one) orders it against sibling processes.
        # Both are needed: the compare and the write have to be one step, or a
        # sibling's rotation lands between them and we overwrite it with a
        # credential the server has already revoked.
        async with self._acache_transaction():
            try:
                existing = await self.cache.aload()
            except Exception:
                existing = None

            if (
                existing is not None
                and not fresh_from_grant
                and self._is_stale_auth(fakts, existing)
            ):
                logger.debug(
                    "Skipping cache write: the cache holds a newer credential than "
                    "the one we are about to persist."
                )
                return

            try:
                await self.cache.aset(fakts)
                self._cache_write_failed = False
            except Exception:
                if not self._cache_write_failed:
                    self._cache_write_failed = True
                    logger.error(
                        "Could not persist the fakts to the cache. If a refresh token "
                        "was just rotated, the credential on disk is now revoked and "
                        "the next start of this app will need to authenticate again.",
                        exc_info=True,
                    )

    def _acache_transaction(self) -> Any:
        """The cache's cross-process transaction, or a no-op.

        ``atransaction`` is optional on :class:`FaktsCache` so that caches with
        nothing to serialize — NoCache, in-memory ones, QSettings — need not
        implement it.
        """
        transaction = getattr(self.cache, "atransaction", None)
        if transaction is None:
            return contextlib.nullcontext()
        return transaction()

    @staticmethod
    def _is_stale_auth(candidate: ActiveFakts, existing: ActiveFakts) -> bool:
        """Whether ``candidate`` would overwrite a newer credential.

        An absent ``refresh_issued_at`` means *unknown*, not "issued at the
        epoch". Coercing it to 0.0 made every freshly injected EnvGrant
        credential look older than whatever was already cached, so a
        re-provisioned container would refuse to persist its new token and
        then adopt the stale one back.

        But "unknown" must not mean "safe to write" either. Only
        :func:`fakts_next.oauth2.merge_token_response` ever stamps this
        field, so *every* credential straight from a grant carries ``None`` —
        which turned the guard off in exactly the case it was written for. An
        untimed candidate therefore loses to a timed one; the caller that
        legitimately needs to install a fresh grant says so explicitly via
        ``fresh_from_grant``.
        """
        if candidate.auth.refresh_token == existing.auth.refresh_token:
            return False
        candidate_at = candidate.auth.refresh_issued_at
        existing_at = existing.auth.refresh_issued_at
        if existing_at is None:
            # Nothing to lose to: the cache itself is untimed.
            return False
        if candidate_at is None:
            # The cache holds a credential someone demonstrably rotated and
            # we cannot show ours is newer. Yield rather than revoke it.
            return True
        return candidate_at < existing_at

    def _token_is_valid(self) -> bool:
        """Check whether the loaded token exists and is not (about to be) expired.

        ``_token_expires_at`` already has the safety skew folded in (see
        :func:`fakts_next.oauth2.resolve_expiry`, which clamps it so a
        short-lived token is neither treated as eternal nor as instantly
        stale). ``None`` means the server declared no lifetime, so the token
        is opaque and we only find out by being rejected.
        """
        if not self.loaded_token:
            return False
        if self._token_expires_at is None:
            return True
        return time.time() < self._token_expires_at

    async def arefresh_token(self, stale_token: Optional[str] = None) -> str:
        """Renew the access token (async).

        Never interactive: this is what a transport layer calls after a 401,
        and a browser opening in the middle of an unrelated request is not
        an acceptable outcome.

        ``stale_token`` makes repeated 401s idempotent. Transports retry a
        rejected operation several times, and each retry that reached the
        token endpoint would rotate the refresh token again — burning
        credentials and worsening contention — even though the first renewal
        already produced a good token. Passing the token that was rejected
        lets us notice it is no longer the current one and hand back what we
        already have.
        """
        self._ensure_entered()
        assert self._token_lock is not None
        async with self._token_lock:
            if (
                stale_token is not None
                and self.loaded_token is not None
                and self.loaded_token != stale_token
            ):
                return self.loaded_token
            return await self._afetch_token(interactive=False)

    async def aget_token(self, interactive: bool = False) -> str:
        """Get the authentication token for a service (async)

        Returns the currently loaded token, renewing it if it is missing
        or expired.
        """
        self._ensure_entered()
        assert self._token_lock is not None
        async with self._token_lock:
            if not self._token_is_valid():
                # Load before deciding to renew: the cache may already hold a
                # perfectly good access token that a sibling process obtained,
                # and renewing on top of it would rotate for nothing.
                await self._aensure_loaded()

            if self._token_is_valid() and self.loaded_token:
                return self.loaded_token

            # ALWAYS lets an ordinary token fetch prompt; the default policy
            # confines that to an explicit load.
            permit = interactive or self.reauth_policy is ReauthPolicy.ALWAYS
            return await self._afetch_token(interactive=permit)

    async def achallenge_alias(
        self, alias: Alias, challenge_key: Optional[ChallengeKey] = None
    ) -> bool:
        """Challenge a single alias (async)

        Without a challenge key, the alias' challenge path must answer
        with a 200. With one, a random nonce is sent along and the
        response must additionally carry a valid signature over it (see
        :mod:`fakts_next.challenge`) — a plain 200 is not enough, so a
        host that merely answers the probe cannot impersonate the service.

        Returns True if the challenge passed, raises otherwise.
        """
        if challenge_key is not None and challenge_key.kind != "ed25519":
            logger.warning(
                "Instance pins a challenge key of unsupported kind '%s'. "
                "Falling back to the plain (unauthenticated) challenge.",
                challenge_key.kind,
            )
            challenge_key = None

        nonce = generate_nonce() if challenge_key else None

        async with aiohttp.ClientSession(
            connector=(
                aiohttp.TCPConnector(ssl=self.ssl_context) if self.ssl_context else None
            ),
            headers={
                "Accept": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=self.alias_challenge_timeout),
        ) as session:
            async with session.get(
                alias.challenge_path,
                params={"nonce": nonce} if nonce else None,
                # Do not follow redirects. The signed message commits only to
                # the nonce, not to the host that answered, so a host that
                # merely bounces the probe to the genuine service would have
                # the real service sign our nonce and pass verification —
                # while all subsequent traffic goes to the redirector.
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        f"Failed to challenge alias {alias} with status code {resp.status}"
                    )
                    raise FaktsError(
                        f"Challenge of alias '{alias.id}' at {alias.challenge_path} "
                        f"answered with status code {resp.status} (expected 200). "
                        f"Response body: {truncate(body) or '<empty>'}"
                    )

                if challenge_key is not None and nonce is not None:
                    try:
                        data = await resp.json()
                        signature = data["signature"]
                    except Exception:
                        body = await resp.text()
                        raise FaktsError(
                            f"The instance pins a challenge key, but the challenge of "
                            f"alias '{alias.id}' at {alias.challenge_path} did not "
                            f"answer with a signature. "
                            f"Response body: {truncate(body) or '<empty>'}"
                        )

                    if not verify_challenge_signature(challenge_key, nonce, signature):
                        raise FaktsError(
                            f"The challenge of alias '{alias.id}' at "
                            f"{alias.challenge_path} answered with an invalid "
                            f"signature: the host does not hold the service's "
                            f"identity key (possible impersonation or a stale "
                            f"pinned key)."
                        )

                return True

    def _grant_status_for(self, fakts_key: str) -> GrantStatus:
        """The grant status of a requirement key on the loaded fakts.

        An explicit server-reported status wins. Without one, a granted
        instance is unambiguously GRANTED; anything else is UNKNOWN (denied
        and unavailable cannot be told apart without server support).
        """
        if not self.loaded_fakts:
            return GrantStatus.UNKNOWN
        explicit = self.loaded_fakts.statuses.get(fakts_key)
        if explicit is not None:
            return explicit
        instance = self.loaded_fakts.instances.get(fakts_key)
        if instance and instance.aliases:
            return GrantStatus.GRANTED
        return GrantStatus.UNKNOWN

    def _not_granted_why(self, fakts_key: str, service: str) -> str:
        """A human readable clause explaining why no instance was granted"""
        status = self._grant_status_for(fakts_key)
        if status == GrantStatus.DENIED:
            return "the user declined access to it"
        if status == GrantStatus.UNAVAILABLE:
            return f"the deployment does not offer the service '{service}'"
        return (
            "the user may have declined access, or the deployment does not "
            f"offer the service '{service}'"
        )

    def _undeclared_key_error(self, fakts_key: str) -> AliasNotFoundError:
        """The error for a key that is not declared in the manifest"""
        requirement_keys = [req.key for req in (self.manifest.requirements or [])]
        return AliasNotFoundError(
            f"Alias for key '{fakts_key}' not found. "
            f"The manifest of '{self.manifest.identifier}' declares the requirement keys: "
            f"{', '.join(requirement_keys) or 'none'}. "
            f"Resolved aliases: {', '.join(self.alias_map.keys()) or 'none'}. "
            f"Add '{fakts_key}' to the manifest requirements if this app should use it."
        )

    async def _aresolve_requirement(
        self, req: Requirement, omit_challenge: bool = False
    ) -> Tuple[Optional[Alias], AliasReport, Optional[str]]:
        """Resolve a single requirement to a working alias.

        Tries the instance's aliases in order (the first alias is the last
        known good one, see :meth:`arefresh_aliases`) and returns the first
        one that passes its challenge.

        Returns:
            A tuple of (selected alias or None, report, composition error
            message or None). The composition error is only set for
            required services that could not be resolved.
        """
        assert self.loaded_fakts, "Fakts need to be loaded before resolving aliases"

        kind = "optional" if req.optional else "required"

        instance = self.loaded_fakts.instances.get(req.key)
        if not instance:
            reason = (
                f"No instance granted for {kind} service {req.key}: "
                f"{self._not_granted_why(req.key, req.service)}."
            )
            logger.log(logging.WARNING if req.optional else logging.ERROR, reason)
            return (
                None,
                AliasReport(alias_id=None, reason=reason, valid=req.optional),
                None if req.optional else reason,
            )

        if not instance.aliases:
            reason = f"No aliases listed for {kind} service {req.key}."
            logger.log(logging.WARNING if req.optional else logging.ERROR, reason)
            return (
                None,
                AliasReport(alias_id=None, reason=reason, valid=req.optional),
                None if req.optional else reason,
            )

        errors_in_alias: List[str] = []

        for alias in instance.aliases:
            if omit_challenge:
                # If we omit the challenge, we just return the first alias
                return (
                    alias,
                    AliasReport(alias_id=alias.id, reason=None, valid=True),
                    None,
                )

            try:
                challenge_ok = await asyncio.wait_for(
                    self.achallenge_alias(alias, challenge_key=instance.challenge_key),
                    timeout=self.alias_challenge_timeout,
                )
                if challenge_ok:
                    return (
                        alias,
                        AliasReport(alias_id=alias.id, reason=None, valid=True),
                        None,
                    )
            except asyncio.TimeoutError:
                errors_in_alias.append(
                    f"Timeout while challenging alias {alias.id} for service {req.key}."
                )
            except Exception as e:
                errors_in_alias.append(
                    f"Error while challenging alias {alias.challenge_path} for service {req.key}: {str(e)}"
                )

        error_message = (
            f"All {len(instance.aliases)} alias(es) of service {req.key} "
            f"(instance '{instance.identifier}') failed their challenge:\n  - "
            + "\n  - ".join(errors_in_alias)
        )
        return (
            None,
            AliasReport(alias_id=None, reason=error_message, valid=False),
            None if req.optional else error_message,
        )

    async def arefresh_aliases(
        self,
        omit_challenge: bool = False,
        omit_report: bool = False,
    ) -> None:
        """Refresh all aliases (async)

        Resolves every requirement of the manifest to a working alias by
        challenging the instances' aliases (concurrently across
        requirements). The selected alias of each service is moved to the
        front of the instance's alias list and persisted in the cache, so
        the next session challenges the last known good alias first.

        Reporting is best effort: it is skipped when the endpoint does not
        advertise a report url, and errors during the report are caught
        and logged instead of raised.

        Args:
            omit_challenge (bool, optional): Should we omit the challenge? Defaults to False.
            omit_report (bool, optional): Should we omit the report? Defaults to False.

        Raises:
            CompositionError: If a required service could not be resolved.
        """
        self._ensure_entered()
        assert self._alias_lock is not None
        async with self._alias_lock:
            await self._arefresh_aliases_locked(
                omit_challenge=omit_challenge, omit_report=omit_report
            )

    async def _arefresh_aliases_locked(
        self,
        omit_challenge: bool = False,
        omit_report: bool = False,
    ) -> None:
        """As :meth:`arefresh_aliases`, for callers already holding
        ``_alias_lock``.

        The lock lives on the public method rather than here because
        :meth:`aget_alias` already holds it and :class:`asyncio.Lock` is not
        reentrant (L2). Without the split, the public entry point published
        ``alias_map``, ``report_map``, ``_aliases_refreshed`` and
        ``_unchallenged_keys`` — and sorted each instance's alias list *in
        place* — with no synchronization at all, while ``aget_alias`` read
        them under a lock that no writer took.
        """
        fakts = await self._aensure_loaded()

        requirements = self.manifest.requirements or []

        # Take the report token up front, before any alias state is
        # published. Fetching it *after* resolution would be a trap:
        # renewing can adopt a credential another process wrote, which
        # resets the resolved aliases — and doing that between publishing
        # alias_map and reading it back makes a successful resolution look
        # like a failed one. Telemetry must never be able to do that, so it
        # also swallows its own failures rather than blocking resolution.
        report_token: Optional[str] = None
        if not omit_report:
            try:
                report_token = await self.aget_token()
            except Exception:
                logger.debug(
                    "No token available for the alias report; skipping it.",
                    exc_info=True,
                )

        results = await asyncio.gather(
            *(
                self._aresolve_requirement(req, omit_challenge=omit_challenge)
                for req in requirements
            )
        )

        new_alias_map: Dict[str, Alias] = {}
        new_report_map: Dict[str, AliasReport] = {}
        composition_errors: List[str] = []

        for req, (selected_alias, report, error) in zip(requirements, results):
            new_report_map[req.key] = report
            if selected_alias:
                new_alias_map[req.key] = selected_alias
            if error:
                composition_errors.append(error)

        # Publish the new maps atomically, so concurrent readers never see
        # a half-populated alias map.
        self.alias_map = new_alias_map
        self.report_map = new_report_map
        self._aliases_refreshed = True
        if omit_challenge:
            self._unchallenged_keys = self._unchallenged_keys | set(new_alias_map)
        else:
            self._unchallenged_keys = self._unchallenged_keys - set(new_alias_map)

        # Remember the working alias as the preferred one: move it to the
        # front of the instance's alias list and persist it, so the next
        # (cached) session challenges the last known good alias first.
        changed = False
        for key, alias in new_alias_map.items():
            instance = fakts.instances.get(key)
            if instance and instance.aliases and instance.aliases[0].id != alias.id:
                instance.aliases.sort(key=lambda a: a.id != alias.id)
                changed = True
        if changed:
            # Persisting the preferred alias order is an optimization for the
            # next session: a failing cache write must not break this one.
            # It goes through _apersist because this writes the *whole*
            # ActiveFakts — credentials included — and this process may be
            # holding an older refresh token than the one on disk. Writing
            # it blindly would replace a live credential with a revoked one
            # without any refresh having taken place here at all.
            #
            # Persist what is current, not the local captured before the
            # report token was fetched: aget_token() above can rotate the
            # credential (or adopt a sibling's), which rebinds loaded_fakts
            # and leaves `fakts` pointing at a superseded object.
            await self._apersist(self.loaded_fakts or fakts)

        if report_token:
            await self._areport_aliases(fakts, composition_errors, report_token)

        if composition_errors:
            joined_errors = "\n".join(composition_errors)
            raise CompositionError(
                f"Could not resolve all required services for app "
                f"'{self.manifest.identifier}' (deployment "
                f"'{fakts.self.deployment_name}'):\n{joined_errors}\n"
                f"Check that the services are running and reachable from this machine."
            )

    async def _areport_aliases(
        self, fakts: ActiveFakts, composition_errors: List[str], token: str
    ) -> None:
        """Report the alias resolution outcome to the server (best effort).

        Reporting is telemetry and must never break the app: endpoints
        that do not advertise a report url are skipped, and any error
        during the report itself is caught and logged.

        The token is passed in rather than fetched here — see
        :meth:`arefresh_aliases` for why acquiring it at this point would
        corrupt the alias state it is reporting on.
        """
        if not fakts.auth.report_endpoint:
            logger.info(
                "The endpoint does not advertise a report url. Skipping the alias report."
            )
            return

        # The report carries the access token, so it gets the same transport
        # gate as every other credential-bearing call — and must go to the
        # deployment we authenticated against. `report_endpoint` is derived
        # from a server-supplied base_url, so without the origin check a
        # misconfigured (or tampered) document would exfiltrate the bearer
        # token to an unrelated host.
        try:
            oauth2.check_transport(
                fakts.auth.report_endpoint, self.allow_insecure_transport
            )
        except Exception:
            logger.warning(
                "Not reporting alias status: the report endpoint would require "
                "sending the access token over an untrusted transport.",
                exc_info=True,
            )
            return

        if not _same_origin(fakts.auth.report_endpoint, fakts.auth.token_endpoint):
            logger.warning(
                "Not reporting alias status: the report endpoint (%s) is not on the "
                "same origin as the token endpoint this app authenticated against.",
                fakts.auth.report_endpoint,
            )
            return

        report = ReportRequest(
            alias_reports=dict(self.report_map),
            functional=len(composition_errors) == 0,
        )
        logger.debug("Reporting usage: %s", report)

        try:
            async with aiohttp.ClientSession(
                connector=(
                    aiohttp.TCPConnector(ssl=self.ssl_context)
                    if self.ssl_context
                    else None
                ),
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=aiohttp.ClientTimeout(total=REPORT_TIMEOUT),
            ) as session:
                async with session.post(
                    fakts.auth.report_endpoint,
                    json=report.model_dump(),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "Failed to report alias status to %s: status code %s. "
                            "Response body: %s",
                            fakts.auth.report_endpoint,
                            resp.status,
                            truncate(body) or "<empty>",
                        )
                        return
                    data = await resp.json()
                    logger.debug("Reporting usage, got response: %s", data)
        except Exception:
            logger.warning(
                "Could not report alias status to %s. Continuing without reporting.",
                fakts.auth.report_endpoint,
                exc_info=True,
            )

    async def _arefresh_aliases_with_selfheal(
        self,
        omit_challenge: bool = False,
        omit_report: bool = True,
    ) -> None:
        """Refresh the aliases, reloading stale cached fakts once on failure.

        If the alias resolution fails while the fakts were loaded from the
        cache (services may have moved since), the fakts are reloaded from
        the grant and the aliases are resolved once more.
        """
        try:
            await self._arefresh_aliases_locked(
                omit_challenge=omit_challenge, omit_report=omit_report
            )
        except CompositionError:
            if not (self.refetch_on_alias_failure and self._loaded_from_cache):
                raise

            logger.warning(
                "Alias resolution from cached fakts failed. Reloading fakts from the grant and retrying."
            )
            await self.aload(reload=True)
            await self._arefresh_aliases_locked(
                omit_challenge=omit_challenge, omit_report=omit_report
            )

    async def aget_alias(
        self,
        fakts_key: str,
        omit_challenge: bool = False,
        omit_report: bool = False,
        force_refresh: bool = False,
    ) -> Alias:
        """Get the alias for a service key (async)

        Returns the active alias for ``fakts_key``. The first call resolves
        all requirements (challenging aliases); subsequent calls return the
        cached (last used) alias without re-challenging, unless
        ``force_refresh`` is set.

        Args:
            fakts_key (str): The service key to look up in the alias map.
            omit_challenge (bool, optional): Skip the alias challenge. Defaults to False.
            omit_report (bool, optional): Skip reporting alias errors. Defaults to False.
            force_refresh (bool, optional): Re-resolve all aliases even if
                already resolved. Defaults to False.

        Returns:
            Alias: The active alias for the given key.

        Raises:
            AliasNotFoundError: If no alias could be resolved for the key.
        """
        self._ensure_entered()
        assert self._alias_lock is not None
        async with self._alias_lock:
            stale_unchallenged = (
                not omit_challenge and fakts_key in self._unchallenged_keys
            )
            # ``_aliases_refreshed`` has to be part of the fast path, not just
            # the refresh condition below it. The token path invalidates
            # aliases by clearing that flag and deliberately leaving
            # ``alias_map`` alone (it cannot take _alias_lock, see L1) — so a
            # fast path that consults only ``alias_map`` would serve exactly
            # the entries the invalidation was meant to retire.
            if (
                not force_refresh
                and not stale_unchallenged
                and self._aliases_refreshed
                and fakts_key in self.alias_map
            ):
                return self.alias_map[fakts_key]

            if force_refresh or stale_unchallenged or not self._aliases_refreshed:
                try:
                    await self._arefresh_aliases_with_selfheal(
                        omit_challenge=omit_challenge, omit_report=omit_report
                    )
                except CompositionError:
                    # Even if some *other* required service failed, the
                    # requested key may have resolved fine. Only raise if
                    # the requested key itself is unresolved.
                    if fakts_key not in self.alias_map:
                        raise

            if fakts_key in self.alias_map:
                return self.alias_map[fakts_key]

            requirement = next(
                (
                    req
                    for req in (self.manifest.requirements or [])
                    if req.key == fakts_key
                ),
                None,
            )

            if requirement is not None:
                # The key is declared: distinguish "the server did not grant
                # an instance" (expected for declined optional services) from
                # "an instance was granted but is unreachable".
                instance = (
                    self.loaded_fakts.instances.get(fakts_key)
                    if self.loaded_fakts
                    else None
                )
                if instance is None or not instance.aliases:
                    kind = "optional" if requirement.optional else "required"
                    raise ServiceNotGrantedError(
                        f"The {kind} service '{fakts_key}' is declared in the manifest of "
                        f"'{self.manifest.identifier}', but the server did not grant an "
                        f"instance for it "
                        f"({self._not_granted_why(fakts_key, requirement.service)})."
                    )

                report = self.report_map.get(fakts_key)
                if report and report.reason:
                    raise AliasNotFoundError(
                        f"Could not resolve alias for {fakts_key}: {report.reason}"
                    )

            raise self._undeclared_key_error(fakts_key)

    async def aget_alias_or_none(
        self,
        fakts_key: str,
        omit_challenge: bool = False,
        omit_report: bool = False,
        force_refresh: bool = False,
    ) -> Optional[Alias]:
        """Get the alias for a service key, or None if unavailable (async)

        Like :meth:`aget_alias`, but returns None instead of raising when
        the declared service was not granted (the user declined it) or
        could not be resolved (all aliases unreachable). Use this to
        degrade gracefully on optional services:

        ```python
        if alias := await fakts.aget_alias_or_none("kabinet"):
            enable_kabinet_features(alias)
        ```

        An *undeclared* key still raises :class:`AliasNotFoundError` —
        that is a bug in the app, not a runtime condition.
        """
        if not any(req.key == fakts_key for req in (self.manifest.requirements or [])):
            raise self._undeclared_key_error(fakts_key)

        try:
            return await self.aget_alias(
                fakts_key,
                omit_challenge=omit_challenge,
                omit_report=omit_report,
                force_refresh=force_refresh,
            )
        except (CompositionError, AliasNotFoundError):
            return None

    async def aget_grant_status(self, fakts_key: str) -> GrantStatus:
        """Get the grant status for a service key (async)

        Returns the per-requirement status the server reported in the
        claim. Servers that do not report statuses: GRANTED is derived
        from a granted instance, everything else is UNKNOWN (a denial
        cannot be told apart from an unavailable service without server
        support).

        Returns:
            GrantStatus: granted, denied, unavailable or unknown.
        """
        self._ensure_entered()
        await self._aensure_loaded()
        return self._grant_status_for(fakts_key)

    async def agranted(self, fakts_key: str) -> bool:
        """Whether the server granted an instance for a service key (async)

        Granted does not imply reachable: this only checks that an
        instance with aliases was composed for the key, without
        challenging it. Use :meth:`aget_alias` (or
        :meth:`aget_alias_or_none`) to obtain a working alias.
        """
        self._ensure_entered()
        fakts = await self._aensure_loaded()
        instance = fakts.instances.get(fakts_key)
        return bool(instance and instance.aliases)

    async def aget_self_alias(self) -> Alias:
        """Get the alias for the application itself (async)

        Returns the active alias for this application, loading the
        configuration first if it is not already loaded.

        Returns:
            Alias: The active alias for this application.
        """
        self._ensure_entered()
        fakts = await self._aensure_loaded()
        return fakts.self.alias

    def load(self, reload: bool = False) -> ActiveFakts:
        """Load the fakts from the cache or the grant (sync)

        Synchronous wrapper around :meth:`aload`.
        """
        return unkoil(self.aload, reload=reload)

    def refresh_aliases(
        self,
        omit_challenge: bool = False,
        omit_report: bool = False,
    ) -> None:
        """Refresh all aliases (sync)

        Synchronous wrapper around :meth:`arefresh_aliases`. The defaults
        match the async method: reporting used to be suppressed here and not
        there, so the same call behaved differently depending on which
        surface you reached it through.
        """
        return unkoil(
            self.arefresh_aliases,
            omit_challenge=omit_challenge,
            omit_report=omit_report,
        )

    def get_self_alias(self) -> Alias:
        """Get the alias for the application itself (sync)

        Synchronous wrapper around :meth:`aget_self_alias`.
        """
        return unkoil(self.aget_self_alias)

    def get_alias(
        self,
        fakts_key: str,
        omit_challenge: bool = False,
        omit_report: bool = False,
        force_refresh: bool = False,
    ) -> Alias:
        """Get the alias for a service key (sync)

        Synchronous wrapper around :meth:`aget_alias`.

        Args:
            fakts_key (str): The service key to look up in the alias map.
            omit_challenge (bool, optional): Skip the alias challenge. Defaults to False.
            omit_report (bool, optional): Skip reporting alias errors. Defaults to False.
            force_refresh (bool, optional): Re-resolve all aliases even if
                already resolved. Defaults to False.

        Returns:
            Alias: The active alias for the given key.
        """
        return unkoil(
            self.aget_alias,
            fakts_key,
            omit_challenge=omit_challenge,
            omit_report=omit_report,
            force_refresh=force_refresh,
        )

    def get_alias_or_none(
        self,
        fakts_key: str,
        omit_challenge: bool = False,
        omit_report: bool = False,
        force_refresh: bool = False,
    ) -> Optional[Alias]:
        """Get the alias for a service key, or None if unavailable (sync)

        Synchronous wrapper around :meth:`aget_alias_or_none`.
        """
        return unkoil(
            self.aget_alias_or_none,
            fakts_key,
            omit_challenge=omit_challenge,
            omit_report=omit_report,
            force_refresh=force_refresh,
        )

    def get_grant_status(self, fakts_key: str) -> GrantStatus:
        """Get the grant status for a service key (sync)

        Synchronous wrapper around :meth:`aget_grant_status`.
        """
        return unkoil(self.aget_grant_status, fakts_key)

    def granted(self, fakts_key: str) -> bool:
        """Whether the server granted an instance for a service key (sync)

        Synchronous wrapper around :meth:`agranted`.
        """
        return unkoil(self.agranted, fakts_key)

    def get_token(self, interactive: bool = False) -> str:
        """Get the authentication token for a service (sync).

        Returns the loaded token, renewing it if it is missing or expired.

        Raises :class:`NeedsReauthenticationError` when the session can only
        be recovered by a human — pass ``interactive=True`` (and use an
        interactive grant) if prompting is appropriate at this call site, or
        catch it and call :meth:`login`.
        """
        return unkoil(self.aget_token, interactive=interactive)

    def refresh_token(self, stale_token: Optional[str] = None) -> str:
        """Renew the authentication token (sync).

        Synchronous wrapper around :meth:`arefresh_token`, including its
        ``stale_token`` compare-and-swap: pass the token that was just
        rejected so repeated retries collapse into a single renewal instead
        of burning a refresh token each time.
        """
        return unkoil(self.arefresh_token, stale_token=stale_token)

    def login(self) -> ActiveFakts:
        """Ensure this app has a working session, prompting only if it must (sync).

        Synchronous wrapper around :meth:`alogin`.
        """
        return unkoil(self.alogin)

    def logout(self) -> None:
        """Forget this app's session on this machine (sync).

        Synchronous wrapper around :meth:`alogout`, including its contract:
        this does not revoke the credential server-side.
        """
        return unkoil(self.alogout)

    def refresh(self) -> ActiveFakts:
        """Reload the configuration from the grant (sync).

        Synchronous wrapper around :meth:`arefresh`. For recovering a dead
        session, prefer :meth:`login` — this always re-runs the grant.
        """
        return unkoil(self.arefresh)

    async def __aenter__(self) -> "Fakts":
        """Enter the context manager

        This method will set the current fakts context variable to itself,
        create the locks that serialize loading, token fetching and alias
        resolution, and bind the manifest hash to the cache.

        Entering never runs the grant. Loading is lazy (see
        ``allow_auto_load``) or explicit via :meth:`aload` — so entering the
        context cannot open a browser, and a grant that fails does so at the
        call that needed it rather than at the ``async with``.
        """

        # Re-entering would install three *fresh* locks while the outer body
        # may be inside a critical section, orphaning the lock object its
        # holder is waiting on — mutual exclusion would be lost silently, and
        # the inner __aexit__ would then null the locks out from under the
        # outer body. Nothing here needs nesting, so refuse it outright.
        if self._load_lock is not None:
            raise NotEnteredError(
                "This Fakts context is already entered. Enter it once and share "
                "the instance; nesting `async with` on the same object would "
                "silently drop the locks the outer scope is relying on."
            )

        self._context_token = current_fakts_next.set(self)
        self._load_lock = asyncio.Lock()
        self._token_lock = asyncio.Lock()
        self._alias_lock = asyncio.Lock()

        # Everything from here on runs with the contextvar already set, so it
        # has to be unwound by hand on failure: Python does not call __aexit__
        # when __aenter__ raises, and the contextvar and locks would leak.
        try:
            # Bind the manifest hash to the cache (if the cache validates
            # against a hash and none was set explicitly), so that a changed
            # manifest (new scopes, new requirements) invalidates cached fakts.
            # Only bind when the cache carries no hash of its own: a non-empty
            # one was configured deliberately and is not ours to overwrite.
            #
            # Sharp edge, deliberately left: two Fakts with *different*
            # manifests sharing one cache object cannot be told apart here,
            # because an auto-bound hash is indistinguishable from a configured
            # one. The first to enter wins and the second validates against the
            # wrong manifest. Give each Fakts its own cache instance.
            if getattr(self.cache, "hash", None) == "":
                setattr(self.cache, "hash", self.manifest.hash())

            # L4: a refresh-based session is credential state, not just config.
            # Without somewhere to persist it, every restart re-authenticates
            # and every sibling process revokes the others by rotating.
            if isinstance(self.cache, NoCache) and self._grant_requires_interaction():
                logger.warning(
                    "Fakts is configured with NoCache but the grant needs user "
                    "interaction. Refresh tokens rotate on every use, so nothing "
                    "will survive this process and each run will prompt again. "
                    "Use a FileCache for anything but a one-shot script."
                )
        except BaseException:
            self._teardown()
            raise

        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Exit the context manager and clean up.

        The teardown runs in a ``finally`` because it must: leaving the
        context variable pointing at an exited instance hands the next
        ``get_current_fakts_next()`` a corpse whose locks belong to a
        loop that no longer exists. A cache reset that fails (read-only
        directory, sharing violation) must not be able to cause that.
        """
        try:
            if self.delete_on_exit:
                # Same clearing as alogout(), minus the locks: we are on the
                # way out, so nothing else can still be holding them.
                await self._alogout_locked()
        finally:
            self._teardown()

    def _teardown(self) -> None:
        """Release the context variable and invalidate the locks.

        Clearing the locks is what makes ``_ensure_entered`` mean something
        after the block ends. Left in place, a post-exit call either quietly
        succeeds against stale state or fails much later with a confusing
        "attached to a different loop".
        """
        self._load_lock = None
        self._token_lock = None
        self._alias_lock = None
        self._loaded_from_cache = False
        self._cache_write_failed = False

        if self._context_token is not None:
            try:
                current_fakts_next.reset(self._context_token)
            except ValueError:
                # The token was created in a different context (e.g. the
                # koil loop thread): fall back to clearing the variable.
                current_fakts_next.set(None)
            self._context_token = None
        else:
            current_fakts_next.set(None)

    def _repr_html_inline_(self) -> str:
        """(Internal) HTML representation for jupyter"""
        return f"<table><tr><td>grant</td><td>{self.grant.__class__.__name__}</td></tr></table>"


def get_current_fakts_next() -> Fakts:
    """Get the current fakts instance

    This method will return the current fakts instance, or raise an
    exception if no fakts instance is set.

    Returns
    -------
    Fakts
        The current fakts instance
    """
    fakts = current_fakts_next.get()

    if fakts is None:
        raise NoFaktsFound("No fakts instance set in this context")

    return fakts
