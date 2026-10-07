"""Alias resolution: which address of each required service this app uses.

Owns ``alias_lock`` and the alias state (L1, L5 in :mod:`fakts.state`).
Resolving challenges every requirement's aliases, remembers the one that worked
(and persists that preference), and hands the outcome to the report, which the
caller sends once the lock is released.

Requirements are resolved side by side, and so are the aliases of one: the
alias that worked last time is asked first and alone, and the others join in
only if it does not answer at once (:meth:`AliasResolver._arace`). A service
that cannot be reached is remembered as down for a moment, and asked again
on its own rather than with every other service.
"""

import asyncio
import logging
import os
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp

from fakts.errors import (
    AliasAttempt,
    AliasNotFoundError,
    AttemptOutcome,
    ChallengeSignatureError,
    ChallengeStatusError,
    ChallengeUnsignedError,
    CompositionError,
    ServiceFailure,
    ServiceNotGrantedError,
    ServiceUnreachableError,
)
from fakts.mesh import MeshError, MeshRoute, Route
from fakts.models import ActiveFakts, Alias, ChallengeKey, GrantStatus, Instance, Requirement
from fakts.report import AliasReport, PendingReport, areport_aliases
from fakts.session import TokenSession
from fakts.state import SessionState

if TYPE_CHECKING:
    from fakts.fakts import Fakts

logger = logging.getLogger(__name__)

Challenger = Callable[..., Awaitable[bool]]
"""``challenge(alias, challenge_key=..., proxy=...)``: True if the alias
answered as the service, raising otherwise."""

_CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv")

MESH_TRIES = 3
"""How often a mesh alias is challenged while the node it goes through has
only just come up: its first connections wait for the peers to hear of it."""


@dataclass(frozen=True)
class _Resolved:
    """One requirement, resolved or not."""

    alias: Alias | None
    report: AliasReport
    failure: ServiceFailure | None = None


def _classify(error: Exception, proxied: bool = False) -> tuple[AttemptOutcome, str | None]:
    """What kind of failure a challenge's exception is, and a short detail.

    ``proxied``: the challenge went through the mesh proxy. A 502 or 504 is
    then the proxy saying it could not reach the service (in its body, why),
    not the service answering wrongly.
    """
    if isinstance(error, TimeoutError):
        return AttemptOutcome.TIMEOUT, None
    if proxied and isinstance(error, ChallengeStatusError) and error.status in (502, 504):
        return AttemptOutcome.UNREACHABLE, f"the mesh proxy says: {error.body or error.status}"
    if proxied and isinstance(error, aiohttp.ClientHttpProxyError):
        return (
            AttemptOutcome.UNREACHABLE,
            f"the mesh proxy says: {error.status} {error.message}",
        )
    if isinstance(error, ChallengeSignatureError):
        return (
            AttemptOutcome.BAD_SIGNATURE,
            "answered with an invalid signature (the host does not hold the "
            "service's identity key)",
        )
    if isinstance(error, ChallengeUnsignedError):
        return AttemptOutcome.UNSIGNED, "answered without a signature"
    if isinstance(error, ChallengeStatusError):
        return AttemptOutcome.BAD_STATUS, f"answered with status {error.status}"
    # Before the connection errors: a certificate error is one of them.
    if isinstance(
        error, (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError, ssl.SSLError)
    ):
        return AttemptOutcome.TLS, _brief(error)
    if isinstance(error, (aiohttp.ClientConnectionError, OSError)):
        return AttemptOutcome.UNREACHABLE, _brief(error)
    return AttemptOutcome.ERROR, _brief(error)


def _brief(error: Exception) -> str:
    text = str(error)
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def _same_instance(left: Instance | None, right: Instance | None) -> bool:
    """Whether resolving ``right`` would ask what resolving ``left`` asked:
    the same aliases (in any order) against the same identity key."""
    if left is None or right is None:
        return left is right
    return left.challenge_key == right.challenge_key and sorted(
        alias.model_dump_json() for alias in left.aliases
    ) == sorted(alias.model_dump_json() for alias in right.aliases)


def in_container() -> bool:
    """Whether this process runs in a container (docker or podman). Only then
    can a ``docker`` alias be the best one, so only then is it tried first."""
    return any(os.path.exists(marker) for marker in _CONTAINER_MARKERS)


class AliasResolver:
    """Resolves the manifest's requirements to working aliases.

    ``settings`` is the owning :class:`~fakts.fakts.Fakts`, read for its
    settings only. ``challenge`` is the probe seam (``Fakts._achallenge_alias``),
    called at call time so a subclass overriding it is honoured.
    """

    def __init__(
        self,
        state: SessionState,
        session: TokenSession,
        route: MeshRoute,
        settings: "Fakts",
        challenge: Challenger,
    ) -> None:
        self._state = state
        self._session = session
        self._route = route
        self._settings = settings
        self._challenge = challenge

        self.alias_map: dict[str, Alias] = {}
        self.report_map: dict[str, AliasReport] = {}
        self._resolved_gen: int | None = None
        self._unchallenged_keys: set[str] = set()
        """Keys whose alias was accepted without probing it (omit_challenge).
        Serving that back to a caller who *did* want a challenge would silently
        skip the probe -- and, where the instance pins a key, the signature
        check -- for the rest of the process."""
        self._pending_report: PendingReport | None = None
        self._failures: dict[str, ServiceFailure] = {}
        """The services without a working alias, as last resolved."""
        self._failed_at: dict[str, float] = {}
        """When each of them failed (``loop.time()``): not asked again for
        ``alias_retry_after``."""

    @property
    def current(self) -> bool:
        """Whether the aliases were resolved against the current instances."""
        return self._resolved_gen == self._state.instances_gen

    def reset(self) -> None:
        """Forget every resolved alias (logout, or leaving the block)."""
        self.alias_map = {}
        self.report_map = {}
        self._resolved_gen = None
        self._unchallenged_keys = set()
        self._pending_report = None
        self._failures = {}
        self._failed_at = {}

    # ------------------------------------------------------------------ #
    # Grant status                                                       #
    # ------------------------------------------------------------------ #

    def is_granted(self, fakts_key: str) -> bool:
        """Whether an instance with aliases was granted for the key."""
        loaded = self._state.loaded_fakts
        instance = loaded.instances.get(fakts_key) if loaded else None
        return bool(instance and instance.aliases)

    def grant_status_for(self, fakts_key: str) -> GrantStatus:
        """The grant status of a requirement key on the loaded fakts.

        An explicit server-reported status wins. Without one, a granted instance
        is unambiguously GRANTED; anything else is UNKNOWN (denied and
        unavailable cannot be told apart without server support).
        """
        loaded = self._state.loaded_fakts
        if not loaded:
            return GrantStatus.UNKNOWN
        explicit = loaded.statuses.get(fakts_key)
        if explicit is not None:
            return explicit
        instance = loaded.instances.get(fakts_key)
        if instance and instance.aliases:
            return GrantStatus.GRANTED
        return GrantStatus.UNKNOWN

    def _not_granted_why(self, fakts_key: str, service: str) -> str:
        """A human readable clause explaining why no instance was granted."""
        status = self.grant_status_for(fakts_key)
        if status == GrantStatus.DENIED:
            return "the user declined access to it"
        if status == GrantStatus.UNAVAILABLE:
            return f"the deployment does not offer the service '{service}'"
        return (
            "the user may have declined access, or the deployment does not "
            f"offer the service '{service}'"
        )

    def undeclared_key_error(self, fakts_key: str) -> AliasNotFoundError:
        """The error for a key that is not declared in the manifest."""
        manifest = self._state.manifest
        requirement_keys = [req.key for req in (manifest.requirements or [])]
        return AliasNotFoundError(
            f"Alias for key '{fakts_key}' not found. "
            f"The manifest of '{manifest.identifier}' declares the requirement keys: "
            f"{', '.join(requirement_keys) or 'none'}. "
            f"Resolved aliases: {', '.join(self.alias_map.keys()) or 'none'}. "
            f"Add '{fakts_key}' to the manifest requirements if this app should use it."
        )

    # ------------------------------------------------------------------ #
    # Lookups (take alias_lock; report after releasing it)               #
    # ------------------------------------------------------------------ #

    async def aget_alias(
        self,
        fakts_key: str,
        omit_challenge: bool = False,
        omit_report: bool = False,
        force_refresh: bool = False,
    ) -> Alias:
        """The active alias for ``fakts_key``; see :meth:`Fakts.aget_alias`."""
        state = self._state
        state.ensure_entered()
        # Without the lock: the maps are only ever replaced whole, and a
        # service being challenged (seconds, if it is down) must not hold up
        # the lookup of one that is long resolved.
        if not force_refresh and (alias := self._resolved(fakts_key, omit_challenge)):
            return alias
        assert state.alias_lock is not None
        try:
            async with state.alias_lock:
                return await self._aget_alias_locked(
                    fakts_key, omit_challenge, omit_report, force_refresh
                )
        finally:
            await self.aflush_report()

    def _resolved(self, fakts_key: str, omit_challenge: bool) -> Alias | None:
        """The key's alias, if it is resolved and may be served as it is.

        `current` has to be part of this, not just of the decision to
        refresh: invalidation bumps the generation and leaves the maps alone
        (L5), so a lookup consulting only alias_map would serve exactly the
        entries the invalidation was meant to retire.
        """
        if not self.current:
            return None
        if not omit_challenge and fakts_key in self._unchallenged_keys:
            return None
        return self.alias_map.get(fakts_key)

    async def arefresh_aliases(
        self, omit_challenge: bool = False, omit_report: bool = False
    ) -> None:
        """Resolve every requirement again; see :meth:`Fakts.arefresh_aliases`."""
        state = self._state
        state.ensure_entered()
        assert state.alias_lock is not None
        try:
            async with state.alias_lock:
                await self._arefresh_locked(omit_challenge=omit_challenge, omit_report=omit_report)
        finally:
            await self.aflush_report()

    async def aflush_report(self) -> None:
        """Send the report of the last resolution, if any, outside every lock."""
        pending, self._pending_report = self._pending_report, None
        if pending is not None:
            await areport_aliases(
                pending,
                ssl_context=self._settings.ssl_context,
                allow_insecure_transport=self._settings.allow_insecure_transport,
            )

    async def _aget_alias_locked(
        self,
        fakts_key: str,
        omit_challenge: bool,
        omit_report: bool,
        force_refresh: bool,
    ) -> Alias:
        if not force_refresh and (alias := self._resolved(fakts_key, omit_challenge)):
            return alias

        stale_unchallenged = not omit_challenge and fakts_key in self._unchallenged_keys
        if force_refresh or stale_unchallenged or not self.current:
            try:
                await self._arefresh_with_selfheal(
                    omit_challenge=omit_challenge, omit_report=omit_report
                )
            except CompositionError:
                # Even if some *other* required service failed, the requested
                # key may have resolved fine -- or not have been granted at all,
                # which has its own error below. Only the requested key's own
                # failure is this composition error.
                if fakts_key not in self.alias_map and self.is_granted(fakts_key):
                    raise
        elif fakts_key not in self.alias_map and self.is_granted(fakts_key):
            # A granted key that failed to resolve last time (its service was
            # briefly down) is tried again, not failed for the process's life:
            # but on its own, and not on every lookup.
            if (failure := self._remembered(fakts_key)) is not None:
                raise self._error_for(failure)
            await self._aresolve_one(fakts_key, omit_challenge, omit_report)

        if fakts_key in self.alias_map:
            return self.alias_map[fakts_key]

        manifest = self._state.manifest
        requirement = next(
            (req for req in (manifest.requirements or []) if req.key == fakts_key),
            None,
        )
        if requirement is not None:
            # The key is declared: distinguish "the server did not grant an
            # instance" (expected for declined optional services) from "an
            # instance was granted but is unreachable".
            if not self.is_granted(fakts_key):
                kind = "optional" if requirement.optional else "required"
                raise ServiceNotGrantedError(
                    f"The {kind} service '{fakts_key}' is declared in the manifest of "
                    f"'{manifest.identifier}', but the server did not grant an "
                    f"instance for it "
                    f"({self._not_granted_why(fakts_key, requirement.service)})."
                )

            if (failure := self._failures.get(fakts_key)) is not None:
                raise ServiceUnreachableError(
                    f"Could not resolve alias for {fakts_key}: {failure.render()}", failure
                )

        raise self.undeclared_key_error(fakts_key)

    def _remembered(self, fakts_key: str) -> ServiceFailure | None:
        """The key's failure, while it is recent enough not to ask again."""
        failure = self._failures.get(fakts_key)
        failed_at = self._failed_at.get(fakts_key)
        if failure is None or failed_at is None:
            return None
        age = asyncio.get_running_loop().time() - failed_at
        return failure if age < self._settings.alias_retry_after else None

    def _error_for(self, failure: ServiceFailure) -> Exception:
        """What a lookup of a service that failed like this raises."""
        if failure.optional:
            return ServiceUnreachableError(
                f"Could not resolve alias for {failure.key}: {failure.render()}", failure
            )
        return self._composition_error((failure,))

    def _composition_error(self, failures: tuple[ServiceFailure, ...]) -> CompositionError:
        state = self._state
        deployment = state.loaded_fakts.self.deployment_name if state.loaded_fakts else None
        joined = "\n".join(failure.render() for failure in failures)
        return CompositionError(
            f"Could not resolve all required services for app "
            f"'{state.manifest.identifier}' (deployment '{deployment}'):\n{joined}\n"
            f"Check that the services are running and reachable from this machine.",
            failures,
        )

    # ------------------------------------------------------------------ #
    # Resolution (caller holds alias_lock)                               #
    # ------------------------------------------------------------------ #

    async def _arefresh_with_selfheal(
        self, omit_challenge: bool = False, omit_report: bool = True
    ) -> None:
        """Resolve, reloading stale cached fakts once on failure.

        If resolution fails while the fakts came from the cache (services may
        have moved since), the fakts are reloaded from the grant and resolved
        once more -- but only for a grant that needs no human: re-running an
        interactive grant opens a browser and replaces the client, severing
        sibling processes, and a failed lookup is never reason enough
        (ReauthPolicy governs that, via alogin()).

        Only what the reload changed is challenged again: an instance that
        came back with the aliases it had keeps the outcome it had, so a
        service that is simply down is not waited for a second time.
        """
        state = self._state
        try:
            await self._arefresh_locked(omit_challenge=omit_challenge, omit_report=omit_report)
        except CompositionError:
            if not (
                self._settings.refetch_on_alias_failure
                and state.loaded_from_cache
                and not state.grant_requires_interaction()
            ):
                raise

            logger.warning(
                "Alias resolution from cached fakts failed. Reloading fakts from the "
                "grant and retrying."
            )
            previous = state.loaded_fakts
            await state.aload(reload=True)
            await self._arefresh_locked(
                omit_challenge=omit_challenge, omit_report=omit_report, previous=previous
            )

    async def _areport_token(self, omit_report: bool) -> str | None:
        """The token the report is sent with, taken before anything resolves.

        Fetching it *after* resolution would be a trap: renewing can adopt a
        credential another process wrote, which invalidates the resolved
        aliases. Telemetry must never be able to do that, so it also swallows
        its own failures rather than blocking resolution.
        """
        if omit_report:
            return None
        try:
            return await self._session.aget_token()
        except Exception:
            logger.debug("No token available for the alias report; skipping it.", exc_info=True)
            return None

    async def _arefresh_locked(
        self,
        omit_challenge: bool = False,
        omit_report: bool = False,
        previous: ActiveFakts | None = None,
    ) -> None:
        """Resolve every requirement and publish the outcome.

        ``previous`` is the configuration the standing outcome was resolved
        against (the self-heal's): requirements whose instance did not
        change keep that outcome unasked.
        """
        state = self._state
        fakts = await state.aensure_loaded()
        requirements = state.manifest.requirements or []
        report_token = await self._areport_token(omit_report)

        # The token fetch above may have rotated or adopted a credential, which
        # rebinds loaded_fakts (with possibly different instances): resolve
        # against what is current, and remember which generation that was.
        fakts = state.loaded_fakts or fakts
        generation = state.instances_gen

        def standing(req: Requirement) -> _Resolved | None:
            if previous is None or req.key not in self.report_map:
                return None
            instance = fakts.instances.get(req.key)
            if instance is None or not _same_instance(previous.instances.get(req.key), instance):
                return None
            return _Resolved(
                self.alias_map.get(req.key),
                self.report_map[req.key],
                self._failures.get(req.key),
            )

        async def resolve(req: Requirement) -> _Resolved:
            return standing(req) or await self._aresolve_requirement(
                fakts, req, omit_challenge=omit_challenge
            )

        results = await asyncio.gather(*(resolve(req) for req in requirements))

        now = asyncio.get_running_loop().time()
        new_alias_map: dict[str, Alias] = {}
        new_report_map: dict[str, AliasReport] = {}
        failures: dict[str, ServiceFailure] = {}
        for req, resolved in zip(requirements, results, strict=True):
            new_report_map[req.key] = resolved.report
            if resolved.alias:
                new_alias_map[req.key] = resolved.alias
            if resolved.failure:
                failures[req.key] = resolved.failure
        required = tuple(failure for failure in failures.values() if not failure.optional)

        # Publish atomically, so concurrent readers never see a half-populated
        # map. Current only while the generation stands (L5).
        self.alias_map = new_alias_map
        self.report_map = new_report_map
        self._resolved_gen = generation
        self._failures = failures
        self._failed_at = dict.fromkeys(failures, now)
        if omit_challenge:
            self._unchallenged_keys = self._unchallenged_keys | set(new_alias_map)
        else:
            self._unchallenged_keys = self._unchallenged_keys - set(new_alias_map)

        await self._apersist_preferred(fakts, new_alias_map)

        if report_token:
            # Sent by the caller once alias_lock is released: a slow report
            # endpoint must not stall every alias lookup in the process. A later
            # resolution (the self-heal retry) replaces this one.
            self._pending_report = PendingReport(
                fakts=fakts,
                report_map=dict(new_report_map),
                functional=not required,
                token=report_token,
            )

        if required:
            raise self._composition_error(required)

    async def _aresolve_one(self, fakts_key: str, omit_challenge: bool, omit_report: bool) -> None:
        """Resolve one requirement again and merge its outcome into the
        published ones; raises what a lookup of it raises if it failed.

        The other services stand as they are: they were not asked, and a
        service that is down must not cost them their aliases (or everyone
        the wait for its challenges).
        """
        state = self._state
        fakts = await state.aensure_loaded()
        requirement = next(
            (req for req in (state.manifest.requirements or []) if req.key == fakts_key),
            None,
        )
        if requirement is None:
            return
        report_token = await self._areport_token(omit_report)
        if not self.current:
            # The token fetch adopted another credential: nothing published
            # is current any more, so there is nothing to merge into.
            try:
                await self._arefresh_locked(omit_challenge=omit_challenge, omit_report=omit_report)
            except CompositionError:
                if fakts_key not in self.alias_map and self.is_granted(fakts_key):
                    raise
            return

        fakts = state.loaded_fakts or fakts
        resolved = await self._aresolve_requirement(
            fakts, requirement, omit_challenge=omit_challenge
        )

        # Copies, swapped in: a reader never sees a map half changed.
        alias_map = {key: alias for key, alias in self.alias_map.items() if key != fakts_key}
        failures = {key: f for key, f in self._failures.items() if key != fakts_key}
        failed_at = {key: at for key, at in self._failed_at.items() if key != fakts_key}
        if resolved.alias:
            alias_map[fakts_key] = resolved.alias
        if resolved.failure:
            failures[fakts_key] = resolved.failure
            failed_at[fakts_key] = asyncio.get_running_loop().time()
        self.alias_map = alias_map
        self.report_map = {**self.report_map, fakts_key: resolved.report}
        self._failures = failures
        self._failed_at = failed_at
        if omit_challenge and resolved.alias:
            self._unchallenged_keys = self._unchallenged_keys | {fakts_key}
        else:
            self._unchallenged_keys = self._unchallenged_keys - {fakts_key}

        if resolved.alias:
            await self._apersist_preferred(fakts, {fakts_key: resolved.alias})
        if report_token:
            self._pending_report = PendingReport(
                fakts=fakts,
                report_map=dict(self.report_map),
                functional=all(failure.optional for failure in failures.values()),
                token=report_token,
            )
        if resolved.failure:
            raise self._error_for(resolved.failure)

    async def _apersist_preferred(self, fakts: ActiveFakts, resolved: dict[str, Alias]) -> None:
        """Remember each working alias as its instance's first.

        The next (cached) session then challenges the last known good alias
        first. It goes through apersist because this writes the *whole*
        ActiveFakts -- credentials included -- and this process may be holding
        an older refresh token than the one on disk (L3). A copy, swapped in
        under load_lock: loaded_fakts is only ever replaced there, never sorted
        in place from the alias path.
        """
        reordered: dict[str, Instance] = {}
        for key, alias in resolved.items():
            instance = fakts.instances.get(key)
            if instance and instance.aliases and instance.aliases[0].id != alias.id:
                reordered[key] = instance.model_copy(
                    update={"aliases": sorted(instance.aliases, key=lambda a: a.id != alias.id)}
                )
        if not reordered:
            return
        state = self._state
        assert state.load_lock is not None
        async with state.load_lock:
            current = state.loaded_fakts or fakts
            updated = current.model_copy(update={"instances": {**current.instances, **reordered}})
            state.loaded_fakts = updated
            await state.apersist_locked(updated)

    async def _aresolve_requirement(
        self,
        fakts: ActiveFakts,
        req: Requirement,
        omit_challenge: bool = False,
    ) -> _Resolved:
        """Resolve a single requirement to a working alias.

        The aliases are challenged as :meth:`_arace` describes, and the one
        that passes is returned: a mesh alias carrying the mesh route's proxy
        and, if this process runs it, its node (for
        ``Alias.aforward``/``aturn``). Unchallenged (``omit_challenge``), the
        first alias that needs nothing started is taken
        (:meth:`_aselect_unchallenged`).

        A failure is only a composition error for a required service; either
        way it says which aliases were tried and how each challenge ended.
        """
        kind = "optional" if req.optional else "required"
        level = logging.WARNING if req.optional else logging.ERROR

        def failed(failure: ServiceFailure) -> _Resolved:
            reason = failure.render()
            logger.log(level, reason)
            return _Resolved(None, AliasReport(alias_id=None, reason=reason, valid=False), failure)

        instance = fakts.instances.get(req.key)
        if not instance or not instance.aliases:
            reason = (
                f"No aliases listed for {kind} service {req.key}."
                if instance
                else f"No instance granted for {kind} service {req.key}: "
                f"{self._not_granted_why(req.key, req.service)}."
            )
            logger.log(level, reason)
            # Nothing granted is no failure of an optional service: it reports
            # as valid, and a lookup says "not granted", not "unreachable".
            return _Resolved(
                None,
                AliasReport(alias_id=None, reason=reason, valid=req.optional),
                None
                if req.optional
                else ServiceFailure(
                    key=req.key,
                    service=req.service,
                    optional=False,
                    instance=instance.identifier if instance else None,
                    reason=reason,
                ),
            )

        if self._route.forced and not any(alias.is_mesh() for alias in instance.aliases):
            return failed(
                ServiceFailure(
                    key=req.key,
                    service=req.service,
                    optional=req.optional,
                    instance=instance.identifier,
                    reason=(
                        f"The {kind} service {req.key} (instance '{instance.identifier}') "
                        f"lists no alias on the mesh, and the mesh is forced: its "
                        f"{len(instance.aliases)} other alias(es) were not tried."
                    ),
                )
            )

        if omit_challenge:
            selected, attempts = await self._aselect_unchallenged(fakts, instance)
        else:
            selected, attempts = await self._arace(fakts, instance)

        for attempt in attempts:
            if attempt.outcome is AttemptOutcome.BAD_SIGNATURE:
                # Also when another alias works: this one is not the service.
                logger.warning(
                    "Alias %s of service %s at %s answered its challenge with a signature "
                    "that does not verify: either that host is not the service, or the "
                    "pinned key is stale.",
                    attempt.alias_id,
                    req.key,
                    attempt.url,
                )
        if selected is None:
            return failed(
                ServiceFailure(
                    key=req.key,
                    service=req.service,
                    optional=req.optional,
                    instance=instance.identifier,
                    attempts=tuple(attempts),
                )
            )

        lost = [a for a in attempts if a.outcome not in (AttemptOutcome.OK, AttemptOutcome.SKIPPED)]
        if lost:
            logger.info(
                "Service %s is reached at alias %s (%s)",
                req.key,
                selected.id,
                "; ".join(f"{a.alias_id} {a.describe()}" for a in lost),
            )
        return _Resolved(selected, AliasReport(alias_id=selected.id, reason=None, valid=True))

    async def _aselect_unchallenged(
        self, fakts: ActiveFakts, instance: Instance
    ) -> tuple[Alias | None, list[AliasAttempt]]:
        """The alias to use when nothing is challenged: the first listed.

        A mesh alias still needs its route, so one listed ahead of a plain
        alias is only taken if the route costs nothing. A docker alias is
        never picked over another: unchallenged, nothing would tell that this
        container is not in that deployment.
        """
        forced = self._route.forced
        docker = [alias for alias in instance.aliases if alias.kind == "docker" and not forced]
        waiting: list[Alias] = []
        for alias in instance.aliases:
            if alias.kind == "docker" or (forced and not alias.is_mesh()):
                continue
            if not alias.is_mesh():
                return alias, []
            if (route := self._route.ready()) is not None:
                # A copy: the route is this process's, never the cached instance's.
                return alias.through_mesh(*route), []
            waiting.append(alias)

        attempts: list[AliasAttempt] = []
        if waiting:
            proxy, node, error = await self._route.aroute(fakts)
            if proxy is not None:
                return waiting[0].through_mesh(proxy, node), []
            attempts = [self._off_the_mesh(alias, error) for alias in waiting]
        if docker:
            return docker[0], attempts
        return None, attempts

    async def _arace(
        self, fakts: ActiveFakts, instance: Instance
    ) -> tuple[Alias | None, list[AliasAttempt]]:
        """Challenge an instance's aliases; the one to use, and what came of each.

        The first alias (the last known good one) is challenged alone for
        ``alias_head_start``. If it passes in that time nothing else is
        asked, so a service that is where it was costs one request. If it
        fails, or has not answered by then, every other alias is challenged
        alongside it and the first to pass is used (the earlier listed, if
        two pass together): aliases that do not answer cost one timeout
        between them, not one each.

        Where the mesh is forced (``force`` on the mesh configuration) only
        the mesh aliases take part, and the node is started at once. Otherwise
        a node is not started to reach what is reachable without one. While
        it is not running, mesh aliases wait until every other alias failed,
        and only then is the node started for them -- except where a mesh
        alias is the first one: that service was last reached over the mesh,
        so the node is started once the head start has passed without a
        direct alias answering (which may still pass first, and is then
        used). A proxy, or a node another service already started, costs
        nothing, so then a mesh alias is challenged like any other.

        Docker aliases (only reachable from inside the deployment's own
        docker environment) are an ordering matter too, the challenge still
        decides: in a container they come first, anywhere else only once the
        others failed (but before a node is started for those).
        """
        loop = asyncio.get_running_loop()
        docker = [alias for alias in instance.aliases if alias.kind == "docker"]
        ordered = [alias for alias in instance.aliases if alias.kind != "docker"]
        left_out: list[Alias] = []
        if self._route.forced:
            # Only what is on the mesh (there is one: the caller saw to it).
            # With nothing else to wait for, the node starts at once.
            left_out = [alias for alias in instance.aliases if not alias.is_mesh()]
            ordered, docker = [alias for alias in ordered if alias.is_mesh()], []
        if docker and in_container():
            ordered, docker = docker + ordered, []
        ranked = list(enumerate(ordered + docker))

        attempts: dict[int, AliasAttempt] = {}
        running: dict[asyncio.Future[AliasAttempt], tuple[int, Alias]] = {}
        waiting: list[tuple[int, Alias]] = []
        """Mesh aliases, until there is a route to challenge them through."""

        def challenge(rank: int, alias: Alias, selected: Alias) -> None:
            task = asyncio.ensure_future(self._aattempt(instance, alias, selected))
            running[task] = (rank, selected)

        def launch(rank: int, alias: Alias) -> None:
            if not alias.is_mesh():
                challenge(rank, alias, alias)
            elif (route := self._route.ready()) is not None:
                # A copy: the route is this process's, never the cached instance's.
                challenge(rank, alias, alias.through_mesh(*route))
            else:
                waiting.append((rank, alias))

        head, queue, late = ranked[:1], ranked[1 : len(ordered)], ranked[len(ordered) :]
        if not ordered:
            head, late = late[:1], late[1:]
        mesh_won_last = head[0][1].is_mesh() and self._route.ready() is None
        deadline = loop.time() + self._settings.alias_head_start
        node: asyncio.Future[Route] | None = None
        node_seen = False
        winner: Alias | None = None
        try:
            launch(*head[0])
            while winner is None:
                now = loop.time()
                if queue and (not running or now >= deadline):
                    for item in queue:
                        launch(*item)
                    queue = []
                if late and not queue and not running:
                    for item in late:
                        launch(*item)
                    late = []
                exhausted = not queue and not late and not running
                if waiting and node is None and (exhausted or (mesh_won_last and now >= deadline)):
                    node = asyncio.ensure_future(self._route.aroute(fakts))
                starting = node is not None and not node_seen
                if not running and not starting:
                    break

                until_deadline = queue or (mesh_won_last and waiting and node is None)
                watched: set[asyncio.Future[AliasAttempt] | asyncio.Future[Route]] = {*running}
                if starting and node is not None:
                    watched.add(node)
                await asyncio.wait(
                    watched,
                    timeout=max(deadline - now, 0) if until_deadline else None,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if starting and node is not None and node.done():
                    node_seen = True
                    proxy, mesh_node, error = node.result()
                    for rank, alias in waiting:
                        if proxy is None:
                            attempts[rank] = self._off_the_mesh(alias, error)
                        else:
                            challenge(rank, alias, alias.through_mesh(proxy, mesh_node))
                    waiting = []
                passed: list[tuple[int, Alias]] = []
                for task in [task for task in running if task.done()]:
                    rank, selected = running.pop(task)
                    attempts[rank] = task.result()
                    if attempts[rank].outcome is AttemptOutcome.OK:
                        passed.append((rank, selected))
                if passed:
                    winner = min(passed, key=lambda item: item[0])[1]
        finally:
            # The challenges nobody waits for any more. Not the node's start:
            # that is the route's own (and shielded), this only stops waiting.
            abandoned = [*running, *([node] if node is not None and not node.done() else [])]
            for task in abandoned:
                task.cancel()
            if abandoned:
                await asyncio.gather(*abandoned, return_exceptions=True)

        for rank, alias in ranked:
            if rank not in attempts:
                attempts[rank] = AliasAttempt(
                    alias.id, alias.kind, alias.challenge_path, AttemptOutcome.SKIPPED
                )
        return winner, [
            *(attempts[rank] for rank, _ in ranked),
            *(
                AliasAttempt(
                    alias.id,
                    alias.kind,
                    alias.challenge_path,
                    AttemptOutcome.SKIPPED,
                    "not tried: the mesh is forced, and this alias is not on it",
                )
                for alias in left_out
            ),
        ]

    def _off_the_mesh(self, alias: Alias, error: MeshError | None) -> AliasAttempt:
        """The attempt of a mesh alias this process has no route to."""
        detail = (
            f"not available: {error}"
            if error is not None
            else "off: pass mesh=MeshOptions() (with fakts[mesh] installed) or "
            'mesh=MeshProxy(url="http://...") to Fakts.'
        )
        return AliasAttempt(
            alias.id, alias.kind, alias.challenge_path, AttemptOutcome.MESH_UNAVAILABLE, detail
        )

    async def _aattempt(self, instance: Instance, alias: Alias, selected: Alias) -> AliasAttempt:
        """Challenge ``selected`` (``alias`` as it is reached) and say how it went."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        tries = 0
        while True:
            tries += 1
            try:
                passed = await asyncio.wait_for(
                    self._probe(alias, instance.challenge_key, selected.proxy),
                    timeout=self._settings.alias_challenge_timeout,
                )
                outcome, detail = (
                    (AttemptOutcome.OK, None) if passed else (AttemptOutcome.REFUSED, None)
                )
            except Exception as e:
                outcome, detail = _classify(e, proxied=bool(selected.proxy))
                logger.debug("Challenge of alias %s at %s: %s", alias.id, alias.challenge_path, e)
            # Through a node that has only just come up, silence may be the
            # peer not knowing of it yet: ask again rather than give up on
            # the one alias that works.
            if (
                outcome is AttemptOutcome.TIMEOUT
                and tries < MESH_TRIES
                and selected.proxy
                and self._route.settling(loop.time())
            ):
                continue
            return AliasAttempt(
                alias.id, alias.kind, alias.challenge_path, outcome, detail, loop.time() - started
            )

    def _probe(
        self, alias: Alias, challenge_key: ChallengeKey | None, proxy: str | None
    ) -> Awaitable[bool]:
        # `proxy` only when set, so challengers without the parameter keep working.
        if proxy:
            return self._challenge(alias, challenge_key=challenge_key, proxy=proxy)
        return self._challenge(alias, challenge_key=challenge_key)
