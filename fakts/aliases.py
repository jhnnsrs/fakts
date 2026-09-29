"""Alias resolution: which address of each required service this app uses.

Owns ``alias_lock`` and the alias state (L1, L5 in :mod:`fakts.state`).
Resolving challenges every requirement's aliases, remembers the one that worked
(and persists that preference), and hands the outcome to the report, which the
caller sends once the lock is released.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fakts.errors import AliasNotFoundError, CompositionError, ServiceNotGrantedError
from fakts.mesh import MeshRoute
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
        assert state.alias_lock is not None
        try:
            async with state.alias_lock:
                return await self._aget_alias_locked(
                    fakts_key, omit_challenge, omit_report, force_refresh
                )
        finally:
            await self.aflush_report()

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
        stale_unchallenged = not omit_challenge and fakts_key in self._unchallenged_keys
        # `current` has to be part of the fast path, not just the refresh
        # condition below it: invalidation bumps the generation and leaves the
        # maps alone (L5), so a fast path consulting only alias_map would serve
        # exactly the entries the invalidation was meant to retire.
        if (
            not force_refresh
            and not stale_unchallenged
            and self.current
            and fakts_key in self.alias_map
        ):
            return self.alias_map[fakts_key]

        # A granted key that failed to resolve last time (its service was
        # briefly down) is tried again, not failed for the process's life.
        unresolved = fakts_key not in self.alias_map and self.is_granted(fakts_key)
        if force_refresh or stale_unchallenged or unresolved or not self.current:
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

            report = self.report_map.get(fakts_key)
            if report and report.reason:
                raise AliasNotFoundError(
                    f"Could not resolve alias for {fakts_key}: {report.reason}"
                )

        raise self.undeclared_key_error(fakts_key)

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
            await state.aload(reload=True)
            await self._arefresh_locked(omit_challenge=omit_challenge, omit_report=omit_report)

    async def _arefresh_locked(
        self, omit_challenge: bool = False, omit_report: bool = False
    ) -> None:
        state = self._state
        fakts = await state.aensure_loaded()
        requirements = state.manifest.requirements or []

        # Take the report token up front, before any alias state is published.
        # Fetching it *after* resolution would be a trap: renewing can adopt a
        # credential another process wrote, which invalidates the resolved
        # aliases. Telemetry must never be able to do that, so it also swallows
        # its own failures rather than blocking resolution.
        report_token: str | None = None
        if not omit_report:
            try:
                report_token = await self._session.aget_token()
            except Exception:
                logger.debug("No token available for the alias report; skipping it.", exc_info=True)

        # The token fetch above may have rotated or adopted a credential, which
        # rebinds loaded_fakts (with possibly different instances): resolve
        # against what is current, and remember which generation that was.
        fakts = state.loaded_fakts or fakts
        generation = state.instances_gen

        results = await asyncio.gather(
            *(
                self._aresolve_requirement(fakts, req, omit_challenge=omit_challenge)
                for req in requirements
            )
        )

        new_alias_map: dict[str, Alias] = {}
        new_report_map: dict[str, AliasReport] = {}
        composition_errors: list[str] = []
        for req, (selected_alias, report, error) in zip(requirements, results, strict=True):
            new_report_map[req.key] = report
            if selected_alias:
                new_alias_map[req.key] = selected_alias
            if error:
                composition_errors.append(error)

        # Publish atomically, so concurrent readers never see a half-populated
        # map. Current only while the generation stands (L5).
        self.alias_map = new_alias_map
        self.report_map = new_report_map
        self._resolved_gen = generation
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
                functional=not composition_errors,
                token=report_token,
            )

        if composition_errors:
            joined_errors = "\n".join(composition_errors)
            raise CompositionError(
                f"Could not resolve all required services for app "
                f"'{state.manifest.identifier}' (deployment "
                f"'{fakts.self.deployment_name}'):\n{joined_errors}\n"
                f"Check that the services are running and reachable from this machine."
            )

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
    ) -> tuple[Alias | None, AliasReport, str | None]:
        """Resolve a single requirement to a working alias.

        Tries the instance's aliases in order (the first is the last known good
        one) and returns the first that passes its challenge. Mesh aliases are
        challenged through the mesh route and returned carrying its proxy and,
        if this process runs it, its node (for ``Alias.aforward``/``aturn``).

        A node is never started to reach what is reachable without one: while
        it is not running, mesh aliases wait until every other alias of the
        service failed, and only then is the node started for them. A proxy,
        or a node another service already started, costs nothing, so then the
        order is kept as it is.

        Returns (selected alias or None, report, composition error or None);
        the composition error is only set for required services.
        """
        kind = "optional" if req.optional else "required"

        instance = fakts.instances.get(req.key)
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

        errors_in_alias: list[str] = []
        waiting_for_mesh: list[Alias] = []
        for alias in instance.aliases:
            selected = alias
            if alias.is_mesh():
                route = self._route.ready()
                if route is None:
                    waiting_for_mesh.append(alias)
                    continue
                # A copy: the route is this process's, never the cached instance's.
                selected = alias.through_mesh(*route)
            if await self._atry(req, instance, alias, selected, omit_challenge, errors_in_alias):
                return (selected, AliasReport(alias_id=alias.id, reason=None, valid=True), None)

        if waiting_for_mesh:
            proxy, node, mesh_error = await self._route.aroute(fakts)
            for alias in waiting_for_mesh:
                if proxy is None:
                    errors_in_alias.append(
                        f"Alias {alias.id} of service {req.key} is only reachable over "
                        f"the mesh, which is not available: {mesh_error}"
                        if mesh_error is not None
                        else f"Alias {alias.id} of service {req.key} is only reachable "
                        f"over the mesh, which is off: pass mesh=MeshOptions() (with "
                        f'fakts[mesh] installed) or mesh=MeshProxy(url="http://...") to Fakts.'
                    )
                    continue
                selected = alias.through_mesh(proxy, node)
                if await self._atry(
                    req, instance, alias, selected, omit_challenge, errors_in_alias
                ):
                    return (
                        selected,
                        AliasReport(alias_id=alias.id, reason=None, valid=True),
                        None,
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

    async def _atry(
        self,
        req: Requirement,
        instance: Instance,
        alias: Alias,
        selected: Alias,
        omit_challenge: bool,
        errors: list[str],
    ) -> bool:
        """Whether ``selected`` (``alias`` as it is reached) passes its
        challenge; why not is appended to ``errors``."""
        if omit_challenge:
            return True
        try:
            if await asyncio.wait_for(
                self._probe(alias, instance.challenge_key, selected.proxy),
                timeout=self._settings.alias_challenge_timeout,
            ):
                return True
        except TimeoutError:
            errors.append(f"Timeout while challenging alias {alias.id} for service {req.key}.")
        except Exception as e:
            errors.append(
                f"Error while challenging alias {alias.challenge_path} for service {req.key}: {e!s}"
            )
        return False

    def _probe(
        self, alias: Alias, challenge_key: ChallengeKey | None, proxy: str | None
    ) -> Awaitable[bool]:
        # `proxy` only when set, so challengers without the parameter keep working.
        if proxy:
            return self._challenge(alias, challenge_key=challenge_key, proxy=proxy)
        return self._challenge(alias, challenge_key=challenge_key)
