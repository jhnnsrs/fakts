"""The Fakts client: configuration, alias resolution and OAuth2 tokens.

:class:`Fakts` is the facade. The work is done by collaborators that share one
:class:`~fakts.state.SessionState` (the loaded configuration, the token and the
three locks, whose invariants L1-L5 are documented there):

- :class:`~fakts.session.TokenSession` -- the token lifecycle;
- :class:`~fakts.aliases.AliasResolver` -- alias resolution and its report;
- :class:`~fakts.mesh.MeshRoute` -- how mesh aliases are reached.
"""

import logging
import ssl
from ssl import SSLContext
from typing import Any, ClassVar

import certifi
from koil.bridge import unkoil
from koil.composition import KoiledModel
from pydantic import Field, PrivateAttr

from fakts import oauth2
from fakts.aliases import AliasResolver
from fakts.cache.nocache import NoCache
from fakts.errors import AliasNotFoundError, CompositionError, FaktsError, NotEnteredError
from fakts.session import ReauthPolicy, TokenSession

from .challenge import generate_nonce, verify_challenge_signature
from .mesh import MeshConfig, MeshRoute
from .models import ActiveFakts, Alias, ChallengeKey, GrantStatus, Manifest
from .protocols import FaktsCache, FaktsGrant
from .report import AliasReport
from .state import SessionState
from .utils import truncate

logger = logging.getLogger(__name__)

__all__ = ["Fakts", "ReauthPolicy"]


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
        from fakts import build_device_code_fakts, Manifest, Requirement

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

    Nothing makes an entered fakts "current": whoever needs it is handed it
    (a runtime hands its own to the clients it builds).
    """

    #: arkitekt_spec.declare.wiring.FAKTS_MARKER: a service parameter typed with this
    #: class is handed the whole client.
    __arkitekt_fakts__: ClassVar[bool] = True

    cache: FaktsCache = Field(default_factory=NoCache, exclude=True)

    manifest: Manifest
    """What the app is and which services it requires."""

    ssl_context: SSLContext = Field(
        default_factory=lambda: ssl.create_default_context(cafile=certifi.where())
    )

    grant: FaktsGrant
    """The grant to load the configuration from"""

    allow_auto_load: bool = Field(default=True, description="Should we autoload on get?")
    """Should we autoload the grants on a call to get?"""

    delete_on_exit: bool = False
    """Should we reset the cache (and loaded state) when exiting the context?"""

    refetch_on_alias_failure: bool = True
    """If resolving required aliases from *cached* fakts fails, should we reload
    the fakts from the grant and retry once? This self-heals stale caches
    (e.g. when services moved since the fakts were cached)."""

    alias_challenge_timeout: float = 3
    """Timeout (in seconds) for a single alias challenge request"""

    reauth_policy: ReauthPolicy = ReauthPolicy.ON_LOGIN
    """When automatic token renewal is allowed to fall back to running the
    grant interactively. The default keeps browsers out of the token path;
    see :class:`ReauthPolicy`."""

    allow_insecure_transport: bool = False
    """Permit sending OAuth2 credentials over plain HTTP to a non-loopback
    host. Fakts supports plain-HTTP deployments on a network, but since v2
    puts a rotating refresh token on the wire it has to be chosen, not
    stumbled into. Loopback never needs this."""

    mesh: MeshConfig | None = None
    """How to reach aliases that are only on the deployment's mesh:
    ``MeshOptions()`` runs a node in this process (``pip install
    "fakts[mesh]"``), started only when a service is reachable no other way;
    the grant should ask for a mesh key with ``request_auth_key`` so a fresh
    node can join. ``MeshOptions(auto=True)`` (the builders' default) does the
    same but stays quiet when the bindings or a key are missing.
    ``MeshProxy(url=...)`` goes through a proxy that is already running.
    Without any, mesh aliases are skipped."""

    _state: SessionState | None = PrivateAttr(default=None)
    _session: TokenSession | None = PrivateAttr(default=None)
    _resolver: AliasResolver | None = PrivateAttr(default=None)
    _mesh_route: MeshRoute | None = PrivateAttr(default=None)

    # ------------------------------------------------------------------ #
    # Shared state                                                       #
    # ------------------------------------------------------------------ #

    def _get_state(self) -> SessionState:
        """The session state, created on first use and kept across re-entry."""
        if self._state is None:
            self._state = SessionState(
                manifest=self.manifest,
                grant=self.grant,
                cache=self.cache,
                allow_auto_load=self.allow_auto_load,
            )
        return self._state

    def _state_session(self) -> TokenSession:
        self._ensure_entered()
        assert self._session is not None
        return self._session

    def _state_resolver(self) -> AliasResolver:
        self._ensure_entered()
        assert self._resolver is not None
        return self._resolver

    @property
    def loaded_fakts(self) -> ActiveFakts | None:
        """The currently loaded configuration."""
        return self._get_state().loaded_fakts

    @property
    def loaded_token(self) -> str | None:
        """The access token currently held."""
        return self._get_state().loaded_token

    @property
    def alias_map(self) -> dict[str, Alias]:
        """The resolved aliases, by requirement key."""
        return self._resolver.alias_map if self._resolver else {}

    @property
    def report_map(self) -> dict[str, AliasReport]:
        """The outcome of the last resolution, by requirement key."""
        return self._resolver.report_map if self._resolver else {}

    def _ensure_entered(self) -> None:
        """Raise if the context manager was not entered yet."""
        if self._state is None or not self._state.entered:
            raise NotEnteredError(
                "You need to enter the Fakts context (`with`/`async with`) before calling this function"
            )

    async def _aensure_loaded(self) -> ActiveFakts:
        """Return the loaded fakts, auto-loading them if allowed."""
        return await self._get_state().aensure_loaded()

    def _grant_requires_interaction(self) -> bool:
        """Whether reloading the grant would need a human."""
        return self._get_state().grant_requires_interaction()

    # ------------------------------------------------------------------ #
    # Loading and the session                                            #
    # ------------------------------------------------------------------ #

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
        return await self._get_state().aload(reload=reload)

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
        state = self._get_state()
        assert state.alias_lock is not None
        assert state.token_lock is not None
        assert state.load_lock is not None
        # Logout is the one operation that legitimately touches all three
        # state domains, so it takes all three locks -- in L1 order.
        async with state.alias_lock, state.token_lock, state.load_lock:
            await self._alogout_locked()

    async def _alogout_locked(self) -> None:
        """Drop every trace of the session. Callers hold the relevant locks.

        Shared with ``delete_on_exit`` so the two cannot drift.
        """
        await self._get_state().areset()
        if self._resolver is not None:
            self._resolver.reset()

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

    # ------------------------------------------------------------------ #
    # Tokens                                                             #
    # ------------------------------------------------------------------ #

    async def _afetch_token(self, interactive: bool = False) -> str:
        """The renewal seam: renew the access token (caller holds token_lock).

        Subclasses may override it (:class:`~fakts.testing.TestingFakts` does);
        the token session calls it at call time.
        """
        return await self._state_session().afetch_token(interactive)

    async def arefresh_token(self, stale_token: str | None = None) -> str:
        """Renew the access token (async); never interactive.

        This is what a transport layer calls after a 401. ``stale_token`` makes
        repeated 401s idempotent: pass the token that was just rejected and a
        renewal that already happened is reused instead of rotating again.
        """
        return await self._state_session().arefresh_token(stale_token)

    async def aget_token(self, interactive: bool = False) -> str:
        """Get the authentication token for a service (async)

        Returns the currently loaded token, renewing it if it is missing or
        expired.
        """
        return await self._state_session().aget_token(interactive)

    # ------------------------------------------------------------------ #
    # Aliases                                                            #
    # ------------------------------------------------------------------ #

    async def _achallenge_alias(
        self,
        alias: Alias,
        challenge_key: ChallengeKey | None = None,
        proxy: str | None = None,
    ) -> bool:
        """Challenge a single alias (async)

        Without a challenge key, the alias' challenge path must answer
        with a 200. With one, a random nonce is sent along and the
        response must additionally carry a valid signature over it (see
        :mod:`fakts.challenge`) — a plain 200 is not enough, so a
        host that merely answers the probe cannot impersonate the service.

        ``proxy`` is the HTTP proxy to challenge through (the mesh proxy,
        for mesh aliases); by default the alias is challenged directly.

        Returns True if the challenge passed, raises otherwise.
        """
        if challenge_key is not None and challenge_key.kind != "ed25519":
            # Fail closed: the instance pins an identity key precisely so that a
            # plain 200 is not enough. Downgrading to it would accept anyone.
            raise FaktsError(
                f"The instance behind alias '{alias.id}' pins a challenge key of kind "
                f"'{challenge_key.kind}', which this fakts cannot verify. Upgrade fakts."
            )

        nonce = generate_nonce() if challenge_key else None

        async with (
            oauth2.client_session(
                self.ssl_context,
                timeout=self.alias_challenge_timeout,
                headers={"Accept": "application/json"},
            ) as session,
            session.get(
                alias.challenge_path,
                params={"nonce": nonce} if nonce else None,
                proxy=proxy,
                # Do not follow redirects. The signed message commits only to
                # the nonce, not to the host that answered, so a host that
                # merely bounces the probe to the genuine service would have
                # the real service sign our nonce and pass verification —
                # while all subsequent traffic goes to the redirector.
                allow_redirects=False,
            ) as resp,
        ):
            if resp.status != 200:
                body = await resp.text()
                raise FaktsError(
                    f"Challenge of alias '{alias.id}' at {alias.challenge_path} "
                    f"answered with status code {resp.status} (expected 200). "
                    f"Response body: {truncate(body) or '<empty>'}"
                )

            if challenge_key is not None and nonce is not None:
                try:
                    data = await resp.json()
                    signature = data["signature"]
                except Exception as err:
                    body = await resp.text()
                    raise FaktsError(
                        f"The instance pins a challenge key, but the challenge of "
                        f"alias '{alias.id}' at {alias.challenge_path} did not "
                        f"answer with a signature. "
                        f"Response body: {truncate(body) or '<empty>'}"
                    ) from err

                if not verify_challenge_signature(challenge_key, nonce, signature):
                    raise FaktsError(
                        f"The challenge of alias '{alias.id}' at "
                        f"{alias.challenge_path} answered with an invalid "
                        f"signature: the host does not hold the service's "
                        f"identity key (possible impersonation or a stale "
                        f"pinned key)."
                    )

            return True

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
        await self._state_resolver().arefresh_aliases(
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
        return await self._state_resolver().aget_alias(
            fakts_key,
            omit_challenge=omit_challenge,
            omit_report=omit_report,
            force_refresh=force_refresh,
        )

    async def aget_alias_or_none(
        self,
        fakts_key: str,
        omit_challenge: bool = False,
        omit_report: bool = False,
        force_refresh: bool = False,
    ) -> Alias | None:
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
            raise self._state_resolver().undeclared_key_error(fakts_key)

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
        return self._state_resolver().grant_status_for(fakts_key)

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

    def get_token(self, interactive: bool = False) -> str:
        """Get the authentication token for a service (sync).

        Returns the loaded token, renewing it if it is missing or expired.

        Raises :class:`NeedsReauthenticationError` when the session can only
        be recovered by a human — pass ``interactive=True`` (and use an
        interactive grant) if prompting is appropriate at this call site, or
        catch it and call :meth:`alogin`.
        """
        return unkoil(self.aget_token, interactive=interactive)

    def refresh_token(self, stale_token: str | None = None) -> str:
        """Renew the authentication token (sync).

        Synchronous wrapper around :meth:`arefresh_token`, including its
        ``stale_token`` compare-and-swap: pass the token that was just
        rejected so repeated retries collapse into a single renewal instead
        of burning a refresh token each time.
        """
        return unkoil(self.arefresh_token, stale_token=stale_token)

    def refresh(self) -> ActiveFakts:
        """Reload the configuration from the grant (sync).

        Synchronous wrapper around :meth:`arefresh`. For recovering a dead
        session, prefer :meth:`alogin` — this always re-runs the grant.
        """
        return unkoil(self.arefresh)

    async def __aenter__(self) -> "Fakts":
        """Enter the context manager

        This creates the locks that serialize loading, token fetching and alias
        resolution, sets up the mesh route, and binds the manifest hash to the
        cache.

        Entering never runs the grant. Loading is lazy (see
        ``allow_auto_load``) or explicit via :meth:`aload` — so entering the
        context cannot open a browser, and a grant that fails does so at the
        call that needed it rather than at the ``async with``.
        """

        # Re-entering would install fresh locks while the outer body may be
        # inside a critical section, orphaning the lock object its holder is
        # waiting on -- mutual exclusion would be lost silently. Nothing here
        # needs nesting, so refuse it outright.
        if self._state is not None and self._state.entered:
            raise NotEnteredError(
                "This Fakts context is already entered. Enter it once and share "
                "the instance; nesting `async with` on the same object would "
                "silently drop the locks the outer scope is relying on."
            )

        state = self._get_state()
        state.enter()
        self._mesh_route = MeshRoute(self.mesh, self.manifest)
        self._session = TokenSession(
            state, self, fetch=lambda interactive: self._afetch_token(interactive)
        )
        self._resolver = AliasResolver(
            state,
            self._session,
            self._mesh_route,
            self,
            challenge=lambda alias, **kwargs: self._achallenge_alias(alias, **kwargs),
        )

        # Everything from here on runs with the locks already set, so it has to
        # be unwound by hand on failure: Python does not call __aexit__ when
        # __aenter__ raises, and the locks would leak.
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
                # FaktsCache declares no hash: only caches that have one bind it.
                setattr(self.cache, "hash", self.manifest.hash())  # noqa: B010

            # L4: a refresh-based session is credential state, not just config.
            # Without somewhere to persist it, every restart re-authenticates
            # and every sibling process revokes the others by rotating.
            if isinstance(self.cache, NoCache) and state.grant_requires_interaction():
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
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        """Exit the context manager and clean up.

        The teardown runs in a ``finally`` because it must: locks left in place
        belong to a loop that no longer exists. A cache reset that fails
        (read-only directory, sharing violation) must not be able to cause that.
        """
        try:
            if self.delete_on_exit:
                # Same clearing as alogout(), minus the locks: we are on the
                # way out, so nothing else can still be holding them.
                await self._alogout_locked()
        finally:
            self._teardown()

    def _teardown(self) -> None:
        """Drop the locks and everything bound to this block.

        Clearing the locks is what makes ``_ensure_entered`` mean something
        after the block ends. Aliases resolved in this block may be bound to
        its mesh node, which closes here; a second ``async with`` resolves
        afresh.
        """
        if self._state is not None:
            self._state.exit()
        if self._resolver is not None:
            self._resolver.reset()
        self._resolver = None
        self._session = None
        if self._mesh_route is not None:
            route, self._mesh_route = self._mesh_route, None
            route.close()

    def _repr_html_inline_(self) -> str:
        """(Internal) HTML representation for jupyter"""
        return f"<table><tr><td>grant</td><td>{self.grant.__class__.__name__}</td></tr></table>"
