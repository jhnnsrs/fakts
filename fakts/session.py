"""The token lifecycle: renewing, rotating, adopting and re-authenticating.

Holds ``token_lock`` (invariants L1-L4 in :mod:`fakts.state`) and nothing
else: the configuration and the token live on the shared
:class:`~fakts.state.SessionState`.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TYPE_CHECKING, Any

import aiohttp

from fakts import oauth2
from fakts.cache.nocache import NoCache
from fakts.errors import FaktsError, NeedsReauthenticationError
from fakts.models import ActiveFakts, AuthFakt
from fakts.state import SessionState

if TYPE_CHECKING:
    from fakts.fakts import Fakts

logger = logging.getLogger(__name__)

REFRESH_TOKEN_MAX_AGE = 30 * 24 * 3600
"""How long a single refresh token is assumed to stay usable. Servers enforce
their own value; this is only used to fail fast with a truthful message instead
of a doomed round trip."""

REFRESH_CHAIN_MAX_AGE = 180 * 24 * 3600
"""How long a refresh *chain* may keep being renewed before the authorization
has to be granted afresh. Rotating does not reset it, which is why even a
permanently running app eventually needs a human."""

REFRESH_RETRY_DELAY = 0.25
REFRESH_RETRY_ROUNDS = 4
MAX_ADOPTIONS = 4
"""How many distinct credentials one renewal will try before giving up.
Bounded by the set of credentials actually seen, so it cannot spin."""

TOKEN_CONNECT_RETRIES = 2
"""How often a refresh is retried when the token endpoint could not be reached
at all (or answered 5xx) -- failures that cannot have rotated the token."""

_REAUTH_REASONS = {
    "idle": "This app's authorization has been unused for too long.",
    "chain_expired": "This app's authorization has reached its maximum age.",
    "superseded": "This app's registration was replaced, most likely by a fresh approval elsewhere.",
    "rejected": "The server rejected this app's stored credential.",
    "exhausted": "None of the stored credentials were accepted.",
}


class ReauthPolicy(str, Enum):
    """When the token path may run an interactive grant on its own.

    A single boolean cannot express this, because the same client is used from
    places with very different tolerances: a 401 inside a GraphQL request must
    never open a browser, while a user typing ``fakts.load()`` at a REPL
    reasonably expects one.
    """

    NEVER = "never"
    """Always raise :class:`NeedsReauthenticationError` instead of prompting."""

    ON_LOGIN = "on_login"
    """The default. Only an explicit ``alogin()`` (or load or refresh) may
    prompt; automatic token renewal never does."""

    ALWAYS = "always"
    """Legacy behaviour: let any token renewal prompt. Convenient for
    single-process interactive apps, hazardous anywhere else."""


class TokenSession:
    """Hands out access tokens and keeps the refresh chain alive.

    ``settings`` is the owning :class:`~fakts.fakts.Fakts`, read for its
    transport and policy settings only. ``fetch`` is the renewal seam
    (``Fakts._afetch_token``), called at call time so a subclass overriding it
    -- :class:`~fakts.testing.TestingFakts` does -- is honoured.
    """

    def __init__(
        self,
        state: SessionState,
        settings: "Fakts",
        fetch: Callable[[bool], Awaitable[str]],
    ) -> None:
        self._state = state
        self._settings = settings
        self._fetch = fetch

    # ------------------------------------------------------------------ #
    # Public entry points (take token_lock)                              #
    # ------------------------------------------------------------------ #

    def token_is_valid(self) -> bool:
        """Whether the loaded token exists and is not (about to be) expired.

        ``token_expires_at`` already has the safety skew folded in (see
        :func:`fakts.oauth2.resolve_expiry`). ``None`` means the server declared
        no lifetime, so the token is opaque and we only find out by being
        rejected.
        """
        state = self._state
        if not state.loaded_token:
            return False
        if state.token_expires_at is None:
            return True
        return time.time() < state.token_expires_at

    async def aget_token(self, interactive: bool = False) -> str:
        """The current access token, renewing it if it is missing or expired."""
        state = self._state
        state.ensure_entered()
        assert state.token_lock is not None
        async with state.token_lock:
            if not self.token_is_valid():
                # Load before deciding to renew: the cache may already hold a
                # perfectly good access token that a sibling process obtained,
                # and renewing on top of it would rotate for nothing.
                await state.aensure_loaded()

            if self.token_is_valid() and state.loaded_token:
                return state.loaded_token

            # ALWAYS lets an ordinary token fetch prompt; the default policy
            # confines that to an explicit load.
            permit = interactive or self._settings.reauth_policy is ReauthPolicy.ALWAYS
            return await self._fetch(permit)

    async def arefresh_token(self, stale_token: str | None = None) -> str:
        """Renew the access token; never interactive.

        ``stale_token`` makes repeated 401s idempotent: transports retry a
        rejected operation several times, and each retry that reached the token
        endpoint would rotate the refresh token again. Passing the token that
        was rejected lets us notice it is no longer the current one and hand
        back what we already have.
        """
        state = self._state
        state.ensure_entered()
        assert state.token_lock is not None
        async with state.token_lock:
            if (
                stale_token is not None
                and state.loaded_token is not None
                and state.loaded_token != stale_token
            ):
                return state.loaded_token
            return await self._fetch(False)

    # ------------------------------------------------------------------ #
    # Renewal (caller holds token_lock, L2)                              #
    # ------------------------------------------------------------------ #

    async def afetch_token(self, interactive: bool = False) -> str:
        """Renew the access token using the refresh grant.

        Must be called while holding ``token_lock`` (L2: nothing here may take
        it again).

        The awkward part is not the HTTP call, it is that refresh tokens
        rotate: every use revokes its predecessor, and sibling processes share
        one cache file. Three cheap measures keep that from turning into a
        stampede, in order of how much they buy:

        1. *Read before refreshing.* Our in-memory token may have been rotated
           away by a sibling hours ago; noticing costs one file read and saves
           a guaranteed-doomed round trip.
        2. *Adopt by untried credential, not by retry count.* A herd of
           processes starting on the same token converges one per round, so a
           fixed "retry once" strands most of them. Looping while the cache
           still offers something we have not tried is self-limiting and
           actually converges.
        3. *Escalate on content, never on a timer.* Giving up because a
           sibling's write had not landed yet would re-run the grant, which
           deletes that sibling's client -- a millisecond of bad luck cascading
           into an outage for everyone.
        """
        state = self._state
        # Note on "never interactive": that contract governs *re*-authentication
        # (see areauthenticate), not the first load. When nothing is loaded yet,
        # aensure_loaded() below runs the grant -- which for a device-code grant
        # can prompt. That is `allow_auto_load`'s decision to make, not this
        # method's, so set allow_auto_load=False if a 401 must never be able to
        # trigger an initial grant.
        fakts = await state.aensure_loaded()

        # (1) our credential may already be stale.
        adopted = await self._aadopt_cached_credentials(set())
        if adopted is not None:
            fakts = adopted
            # The adopted entry may carry an access token that is still good.
            # Spending a rotation on top of it would be pure loss.
            if self.token_is_valid() and state.loaded_token:
                return state.loaded_token

        tried: set[tuple[str, str]] = set()
        # What we came in holding. Every await below can yield to a concurrent
        # aload(reload=True), which replaces loaded_fakts wholesale; comparing
        # against this is how we notice that happened.
        entry_token = state.loaded_token

        for _ in range(MAX_ADOPTIONS):
            # Re-read rather than trusting the local (L3): a reload that landed
            # while we were blocked leaves `fakts` pointing at a revoked
            # credential, and _aadopt_cached_credentials will not rescue us
            # because the cache now matches loaded_fakts.
            fakts = state.loaded_fakts or fakts

            # Deliberately "did it change", never "is it valid": arefresh_token
            # gets here precisely when loaded_token is the token the server just
            # rejected, and a rejected token is usually not expired.
            if (
                state.loaded_token is not None
                and state.loaded_token != entry_token
                and self.token_is_valid()
            ):
                return state.loaded_token

            auth = fakts.auth

            # Cheap local check before spending a round trip, and it yields a
            # truthful message instead of a guess at what went wrong.
            expiry_reason = _classify_refresh_expiry(auth)
            if expiry_reason:
                return await self.areauthenticate(reason=expiry_reason, interactive=interactive)

            tried.add((auth.client_id, auth.refresh_token))

            try:
                data = await self._apost_refresh(auth)
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
                    return await self.areauthenticate(
                        reason=("superseded" if e.error == "invalid_client" else "rejected"),
                        interactive=interactive,
                    )
                fakts = adopted
                # The credential we just adopted may already carry a usable
                # access token -- the sibling that rotated ahead of us got one.
                # Rotating again on top of it would revoke the very token we
                # adopted, which is how a stampede sustains itself.
                if self.token_is_valid() and state.loaded_token:
                    return state.loaded_token
                continue
            except FaktsError:
                raise
            except Exception as e:
                raise FaktsError(
                    f"Could not reach the token endpoint {auth.token_endpoint} to "
                    f"renew the session: {e}"
                ) from e

            return await self._acommit_token_response(fakts, data)

        return await self.areauthenticate(reason="exhausted", interactive=interactive)

    async def _apost_refresh(self, auth: AuthFakt) -> dict[str, Any]:
        """POST the refresh grant, retrying only failures the server never saw.

        A refresh rotates: once the server has processed it, the old token is
        dead, so repeating it after an ambiguous failure (a timeout, a reset
        mid-response) would read as a rejected credential and push the app into
        reauthentication. A connection that never opened, or a 5xx, did not
        rotate anything -- those are retried a couple of times.
        """
        for attempt in range(TOKEN_CONNECT_RETRIES + 1):
            try:
                return await oauth2.arefresh(
                    auth.token_endpoint,
                    client_id=auth.client_id,
                    refresh_token=auth.refresh_token,
                    ssl_context=self._settings.ssl_context,
                    allow_insecure_transport=self._settings.allow_insecure_transport,
                )
            except (aiohttp.ClientConnectorError, oauth2.TransientHTTPError) as e:
                if attempt == TOKEN_CONNECT_RETRIES:
                    raise
                logger.info("Token endpoint unavailable (%s); retrying.", e)
                await asyncio.sleep(REFRESH_RETRY_DELAY * (attempt + 1))
        raise AssertionError("unreachable")

    async def _acommit_token_response(self, previous: ActiveFakts, data: dict[str, Any]) -> str:
        """Persist a rotated credential, *then* start using it.

        The server commits the rotation when it answers, so from that instant
        the old refresh token is dead. If we adopted the new one in memory and
        only then failed to write it, this process would keep working while the
        credential on disk stayed revoked -- a breakage that surfaces at the
        next restart, far from its cause.
        """
        state = self._state
        response = oauth2.parse_token_response(data, previous.auth.token_endpoint)
        candidate = oauth2.merge_token_response(
            previous,
            response,
            token_endpoint=previous.auth.token_endpoint,
            report_endpoint=previous.auth.report_endpoint,
            revocation_endpoint=previous.auth.revocation_endpoint,
            skew=oauth2.TOKEN_EXPIRY_SKEW,
            fallback_client_id=previous.auth.client_id,
        )

        await state.apersist(candidate)

        aliases_changed = oauth2.instances_changed(previous, candidate)

        state.loaded_fakts = candidate
        state.loaded_token = candidate.auth.access_token
        state.token_expires_at = candidate.auth.expires_at

        if aliases_changed:
            state.invalidate_aliases()

        if not state.loaded_token:
            raise FaktsError(
                f"The token endpoint {candidate.auth.token_endpoint} answered "
                f"without an access_token."
            )
        return state.loaded_token

    async def _aawait_untried_credentials(self, tried: set[tuple[str, str]]) -> ActiveFakts | None:
        """Wait briefly for a sibling's rotation to land, then adopt it.

        Terminates for the right reason: we only ever accept a credential we
        have not already tried, so this cannot spin. The sleep is jittered so
        that N processes racing on the same file do not re-read in lockstep.
        """
        if isinstance(self._state.cache, NoCache):
            # Nothing is shared, so no sibling can have written anything: the
            # waits below would only hold token_lock for nothing.
            return None
        for round_index in range(REFRESH_RETRY_ROUNDS):
            adopted = await self._aadopt_cached_credentials(tried)
            if adopted is not None:
                return adopted
            if round_index == REFRESH_RETRY_ROUNDS - 1:
                # Nothing re-reads the cache after this, so sleeping here only
                # holds token_lock -- and every other token consumer -- for
                # nothing.
                break
            await asyncio.sleep(REFRESH_RETRY_DELAY * (1 + random.random()))
        return None

    async def _aadopt_cached_credentials(self, tried: set[tuple[str, str]]) -> ActiveFakts | None:
        """Adopt the cached credential if it is one we have not tried.

        The key is the whole ``(client_id, refresh_token)`` pair, not the token
        alone: re-approval rotates the client identity too, and a refresh token
        is only ever valid for the client it was issued to.

        Called while holding ``token_lock``; takes ``load_lock`` (L1).
        """
        state = self._state
        assert state.load_lock is not None
        async with state.load_lock:
            try:
                cached = await state.cache.aload()
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

            current = state.loaded_fakts
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
            # any alias resolved against the old ones may now point at a service
            # this credential does not reach. Under multi-process load this is
            # the *common* path, not an edge case.
            if current is not None and oauth2.instances_changed(current, cached):
                state.invalidate_aliases()
            state.loaded_fakts = cached
            state.credential_adopted = True
            # Keep the access token that came with it. Discarding it and
            # rotating anyway is the stampede this read-before-refresh step
            # exists to avoid.
            state.loaded_token = None
            state.token_expires_at = None
            state.seed_token_from(cached)
            return cached

    async def areauthenticate(self, *, reason: str, interactive: bool) -> str:
        """Last resort: re-run the grant, but only when that is safe.

        Re-running an *interactive* grant is not a quiet retry. It opens a
        browser and makes the server mint a replacement client, deleting the
        old one -- which severs every sibling process sharing this cache. So it
        happens only when a human actually asked for it.

        Non-interactive grants (redeem, a supplied credential) carry no such
        cost, which is what keeps headless deployments recoverable.
        """
        state = self._state
        policy = self._settings.reauth_policy
        explanation = _REAUTH_REASONS.get(reason, "The session could not be renewed.")

        if not state.grant_requires_interaction():
            logger.info("Re-running the non-interactive grant: %s", explanation)
            await state.aload(reload=True)
            return await self._afetch_after_reload()

        if interactive and policy is not ReauthPolicy.NEVER:
            logger.info("Re-running the interactive grant: %s", explanation)
            await state.aload(reload=True)
            return await self._afetch_after_reload()

        if policy is ReauthPolicy.NEVER:
            raise NeedsReauthenticationError(
                f"{explanation} This app must be authorized again, and "
                f"reauth_policy=ReauthPolicy.NEVER forbids prompting from this "
                f"process: authorize it elsewhere (or provision a fresh credential)."
            )
        raise NeedsReauthenticationError(
            f"{explanation} This app must be authorized again, which needs "
            f"someone at a browser. Call fakts.alogin() when prompting is "
            f"appropriate, or set reauth_policy=ReauthPolicy.ALWAYS to let the "
            f"token path prompt on its own."
        )

    async def _afetch_after_reload(self) -> str:
        """Return the token the freshly reloaded grant produced."""
        state = self._state
        fakts = await state.aensure_loaded()
        if fakts.auth.access_token:
            state.loaded_token = fakts.auth.access_token
            state.token_expires_at = fakts.auth.expires_at
            return fakts.auth.access_token
        raise FaktsError("The grant completed but produced no access token.")


def _classify_refresh_expiry(auth: AuthFakt) -> str | None:
    """Name a locally-detectable expiry, if there is one.

    Servers enforce two independent limits: how long one refresh token stays
    usable, and how long a chain may keep being renewed. Both are computable
    from what we persisted, so we can fail with a true explanation instead of
    asking and then guessing at ``invalid_grant``.
    """
    now = time.time()
    if auth.refresh_issued_at and now - auth.refresh_issued_at > REFRESH_TOKEN_MAX_AGE:
        return "idle"
    if auth.chain_started_at and now - auth.chain_started_at > REFRESH_CHAIN_MAX_AGE:
        return "chain_expired"
    return None
