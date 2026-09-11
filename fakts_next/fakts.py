import asyncio
import contextvars
import logging
import ssl
import time
from ssl import SSLContext
from typing import Any, Dict, List, Optional, Tuple, Type

import aiohttp
import certifi
from oauthlib.common import urldecode
from oauthlib.oauth2.rfc6749.clients.backend_application import BackendApplicationClient
from oauthlib.oauth2.rfc6749.errors import InvalidClientError
from pydantic import BaseModel, Field

from fakts_next.cache.nocache import NoCache
from fakts_next.errors import (
    AliasNotFoundError,
    CompositionError,
    FaktsError,
    NoFaktsFound,
    NotEnteredError,
    ServiceNotGrantedError,
)
from koil.composition import KoiledModel
from koil.bridge import unkoil

from .challenge import generate_nonce, verify_challenge_signature
from .models import (
    ActiveFakts,
    Alias,
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

TOKEN_EXPIRY_SKEW = 30
"""Seconds before the actual expiry at which a token is considered expired"""


class AliasReport(BaseModel):
    alias_id: str | None = None
    reason: str | None = None
    valid: bool = False


class ReportRequest(BaseModel):
    token: str
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

    load_on_enter: bool = False
    """Should we load the fakts when entering the context?"""
    delete_on_exit: bool = False
    """Should we reset the cache (and loaded state) when exiting the context?"""

    refetch_on_alias_failure: bool = True
    """If resolving required aliases from *cached* fakts fails, should we reload
    the fakts from the grant and retry once? This self-heals stale caches
    (e.g. when services moved since the fakts were cached)."""

    alias_challenge_timeout: float = 3
    """Timeout (in seconds) for a single alias challenge request"""

    _load_lock: Optional[asyncio.Lock] = None
    _token_lock: Optional[asyncio.Lock] = None
    _alias_lock: Optional[asyncio.Lock] = None
    _token_expires_at: Optional[float] = None
    _loaded_from_cache: bool = False
    _aliases_refreshed: bool = False
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

            # Persisting is best effort: the fakts are valid even if the
            # cache cannot be written (read-only directory, full disk, ...).
            try:
                await self.cache.aset(self.loaded_fakts)
            except Exception:
                logger.warning(
                    "Could not persist the loaded fakts to the cache. "
                    "Continuing without caching.",
                    exc_info=True,
                )
            return self.loaded_fakts

    async def arefresh(self) -> ActiveFakts:
        """Refresh the fakts (async)

        Reloads the fakts from the grant (bypassing the cache) and updates
        the cache with the result.
        """
        return await self.aload(reload=True)

    async def _afetch_token(self, allow_reload: bool = True) -> str:
        """Fetch a fresh access token via the client credentials flow.

        Must be called while holding ``_token_lock``. On an invalid client
        (e.g. the client was deleted on the server) the fakts are reloaded
        from the grant once, and the fetch is retried.
        """
        fakts = await self._aensure_loaded()

        scope = " ".join(fakts.auth.scopes)

        auth_client = BackendApplicationClient(
            client_id=fakts.auth.client_id,
            scope=scope,
        )

        token_url = fakts.auth.token_url

        body = auth_client.prepare_request_body(
            client_secret=fakts.auth.client_secret,
            client_id=fakts.auth.client_id,
        )

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        }

        data = dict(urldecode(body))

        logger.debug("Challening for token with data %s and headers %s", data, headers)

        # Create an OAuth2 session for the OSF
        async with aiohttp.ClientSession(
            connector=(
                aiohttp.TCPConnector(ssl=self.ssl_context) if self.ssl_context else None
            ),
            headers=headers,
        ) as session:
            async with session.post(
                token_url,
                data=data,
                auth=aiohttp.BasicAuth(
                    fakts.auth.client_id,
                    fakts.auth.client_secret,
                ),
            ) as resp:
                text = await resp.text()
                logger.debug(text)

                try:
                    auth_client.parse_request_body_response(text, scope=scope)
                except InvalidClientError as e:
                    logger.error(
                        f"Invalid client error while trying to get token for {fakts.auth.client_id} with response: {text}. We are trying to reload the fakts."
                    )
                    if not allow_reload:
                        raise FaktsError(
                            f"The token endpoint {token_url} rejected client "
                            f"'{fakts.auth.client_id}' even after re-registering through the grant. "
                            f"Response (status {resp.status}): {truncate(text)}"
                        ) from e

                    if not await self._aadopt_newer_cached_fakts(fakts):
                        await self.aload(reload=True)
                    return await self._afetch_token(allow_reload=False)
                except Exception as e:
                    raise FaktsError(
                        f"Could not obtain a token for client '{fakts.auth.client_id}' "
                        f"from {token_url} (requested scopes: '{scope}'). "
                        f"Response (status {resp.status}): {truncate(text)}"
                    ) from e

                token = auth_client.token
                self.loaded_token = str(token["access_token"])
                expires_at = token.get("expires_at")
                self._token_expires_at = float(expires_at) if expires_at else None
                return self.loaded_token

    async def _aadopt_newer_cached_fakts(self, rejected: ActiveFakts) -> bool:
        """Adopt fakts from the cache if they hold different client
        credentials than the rejected ones.

        When the token endpoint rejects our client, another process sharing
        the cache may already have re-registered the app and stored fresh
        credentials. Re-reading the cache then heals silently, instead of
        re-registering through the grant (which would in turn invalidate the
        other process' client). Must be called while holding ``_token_lock``.

        Returns:
            bool: True if different cached fakts were adopted.
        """
        assert self._load_lock is not None
        async with self._load_lock:
            try:
                cached = await self.cache.aload()
            except Exception:
                logger.warning(
                    "Could not re-read the cache after the client was rejected.",
                    exc_info=True,
                )
                return False

            if not cached:
                return False

            if (
                cached.auth.client_id == rejected.auth.client_id
                and cached.auth.client_secret == rejected.auth.client_secret
            ):
                return False

            logger.info(
                "The cache holds different client credentials than the rejected "
                "ones (probably re-registered by another process). Adopting them "
                "instead of re-registering through the grant."
            )
            self.loaded_fakts = cached
            self._loaded_from_cache = True
            self.loaded_token = None
            self._token_expires_at = None
            self.alias_map = {}
            self.report_map = {}
            self._aliases_refreshed = False
            return True

    def _token_is_valid(self) -> bool:
        """Check whether the loaded token exists and is not (about to be) expired"""
        if not self.loaded_token:
            return False
        if self._token_expires_at is None:
            return True
        return time.time() < self._token_expires_at - TOKEN_EXPIRY_SKEW

    async def arefresh_token(self) -> str:
        """Refresh the authentication token for a service (async)"""
        self._ensure_entered()
        assert self._token_lock is not None
        async with self._token_lock:
            return await self._afetch_token()

    async def aget_token(self) -> str:
        """Get the authentication token for a service (async)

        Returns the currently loaded token, refreshing it if it is missing
        or expired (the expiry from the token response is honored, with a
        small safety skew).
        """
        self._ensure_entered()
        assert self._token_lock is not None
        async with self._token_lock:
            if not self._token_is_valid():
                await self._afetch_token()

            if not self.loaded_token:
                raise FaktsError(
                    "Token fetch did not produce a token. This should not happen — "
                    "please report it as a bug in fakts_next."
                )
            return self.loaded_token

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
        ) as session:
            async with session.get(
                alias.challenge_path,
                params={"nonce": nonce} if nonce else None,
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
        fakts = await self._aensure_loaded()

        requirements = self.manifest.requirements or []

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
            try:
                await self.cache.aset(fakts)
            except Exception:
                logger.warning(
                    "Could not persist the preferred alias order to the cache. "
                    "Continuing without caching.",
                    exc_info=True,
                )

        if not omit_report:
            await self._areport_aliases(fakts, composition_errors)

        if composition_errors:
            joined_errors = "\n".join(composition_errors)
            raise CompositionError(
                f"Could not resolve all required services for app "
                f"'{self.manifest.identifier}' (deployment "
                f"'{fakts.self.deployment_name}'):\n{joined_errors}\n"
                f"Check that the services are running and reachable from this machine."
            )

    async def _areport_aliases(
        self, fakts: ActiveFakts, composition_errors: List[str]
    ) -> None:
        """Report the alias resolution outcome to the server (best effort).

        Reporting is telemetry and must never break the app: endpoints
        that do not advertise a report url are skipped, and any error
        during the report itself is caught and logged.
        """
        if not fakts.auth.report_url:
            logger.info(
                "The endpoint does not advertise a report url. Skipping the alias report."
            )
            return

        report = ReportRequest(
            token=fakts.auth.client_token,
            alias_reports=self.report_map,
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
                },
            ) as session:
                async with session.post(
                    fakts.auth.report_url,
                    json=report.model_dump(),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "Failed to report alias status to %s: status code %s. "
                            "Response body: %s",
                            fakts.auth.report_url,
                            resp.status,
                            truncate(body) or "<empty>",
                        )
                        return
                    data = await resp.json()
                    logger.debug("Reporting usage, got response: %s", data)
        except Exception:
            logger.warning(
                "Could not report alias status to %s. Continuing without reporting.",
                fakts.auth.report_url,
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
            await self.arefresh_aliases(
                omit_challenge=omit_challenge, omit_report=omit_report
            )
        except CompositionError:
            if not (self.refetch_on_alias_failure and self._loaded_from_cache):
                raise

            logger.warning(
                "Alias resolution from cached fakts failed. Reloading fakts from the grant and retrying."
            )
            await self.aload(reload=True)
            await self.arefresh_aliases(
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
            if not force_refresh and fakts_key in self.alias_map:
                return self.alias_map[fakts_key]

            if force_refresh or not self._aliases_refreshed:
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
        omit_report: bool = True,
    ) -> None:
        """Refresh all aliases (sync)

        Synchronous wrapper around :meth:`arefresh_aliases`.
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

    def get_token(self) -> str:
        """Get Authentikation Token for a service (sync)

        This method will return the currently loaded token, or refresh it if it is not
        loaded yet. It will raise an exception if the token could not be loaded.

        Returns:
            str: The currently loaded token
        """
        return unkoil(self.aget_token)

    def refresh_token(self) -> str:
        """Refresh the authentication token for a service (sync)

        Synchronous wrapper around :meth:`arefresh_token`.
        """
        return unkoil(self.arefresh_token)

    async def __aenter__(self) -> "Fakts":
        """Enter the context manager

        This method will set the current fakts context variable to itself,
        create the locks that serialize loading, token fetching and alias
        resolution, bind the manifest hash to the cache, and (if
        ``load_on_enter`` is set) eagerly load the fakts.
        """

        self._context_token = current_fakts_next.set(self)
        self._load_lock = asyncio.Lock()
        self._token_lock = asyncio.Lock()
        self._alias_lock = asyncio.Lock()

        # Bind the manifest hash to the cache (if the cache validates
        # against a hash and none was set explicitly), so that a changed
        # manifest (new scopes, new requirements) invalidates cached fakts.
        if getattr(self.cache, "hash", None) == "":
            setattr(self.cache, "hash", self.manifest.hash())

        if self.load_on_enter:
            await self.aload()

        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Exit the context manager and clean up"""
        if self.delete_on_exit:
            await self.cache.areset()
            self.loaded_fakts = None
            self.loaded_token = None
            self._token_expires_at = None
            self.alias_map = {}
            self.report_map = {}
            self._aliases_refreshed = False

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
