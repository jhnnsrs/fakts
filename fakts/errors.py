"""The errors Fakts raises, and what a failed alias resolution is made of."""

from dataclasses import dataclass
from enum import Enum


class FaktsError(Exception):
    """Base class for all Fakts errors

    This class is used to catch all Fakts errors. If you want to catch
    all Fakts errors, you can catch this class.
    """


class NotEnteredError(FaktsError):
    """Raised when a Fakts method is called before entering the context

    Fakts needs to be used as a (async) context manager. This error is
    raised when a method that requires the context (its locks) is called
    before `__aenter__` was run.
    """


class ChallengeError(FaktsError):
    """Raised when an alias answered its challenge, but not as the service

    The host was reached and said something other than what the service
    would. The subclasses say what: the wrong status, no signature where
    the instance pins a key, or a signature that does not verify.
    """


class ChallengeStatusError(ChallengeError):
    """The challenge was answered with a status other than 200.

    ``body`` is the start of what came with it: through a proxy it is the
    proxy's word on why the service was not reached.
    """

    def __init__(self, message: str, status: int = 0, body: str = "") -> None:
        # All of them to the base, so that the error survives a pickle.
        super().__init__(message, status, body)
        self.status = status
        self.body = body

    def __str__(self) -> str:
        return str(self.args[0])


class ChallengeUnsignedError(ChallengeError):
    """The instance pins a challenge key, but the answer carried no signature."""


class ChallengeSignatureError(ChallengeError):
    """The answer's signature does not verify against the pinned key.

    Either the host is not the service (and must not be used), or the key
    pinned in the cached configuration is stale.
    """


class UnsupportedChallengeKeyError(ChallengeError):
    """The instance pins a challenge key of a kind this fakts cannot verify."""


class AttemptOutcome(Enum):
    """How the challenge of one alias ended."""

    OK = "ok"
    REFUSED = "refused"
    """The challenge ran and said no, without saying why."""
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"
    """No connection: the name did not resolve, or nothing answered there."""
    TLS = "tls"
    BAD_STATUS = "bad_status"
    UNSIGNED = "unsigned"
    BAD_SIGNATURE = "bad_signature"
    MESH_UNAVAILABLE = "mesh_unavailable"
    """A mesh alias, and this process has no way onto the mesh."""
    SKIPPED = "skipped"
    """Not needed: another alias had answered."""
    ERROR = "error"
    """Anything else; ``detail`` names the exception."""


@dataclass(frozen=True)
class AliasAttempt:
    """One alias of a service, and what came of challenging it."""

    alias_id: str
    kind: str | None
    url: str
    outcome: AttemptOutcome
    detail: str | None = None
    seconds: float | None = None
    """How long the challenge took, if one ran."""

    def describe(self) -> str:
        """The outcome in words, e.g. ``timed out after 3.0 s``."""
        took = f" after {self.seconds:.1f} s" if self.seconds is not None else ""
        match self.outcome:
            case AttemptOutcome.OK:
                return "answered"
            case AttemptOutcome.REFUSED:
                return "failed its challenge"
            case AttemptOutcome.TIMEOUT:
                return f"timed out{took}"
            case AttemptOutcome.UNREACHABLE:
                return f"unreachable: {self.detail}"
            case AttemptOutcome.TLS:
                return f"TLS: {self.detail}"
            case AttemptOutcome.SKIPPED:
                return self.detail or "not tried"
            case AttemptOutcome.MESH_UNAVAILABLE:
                return f"only reachable over the mesh, which is {self.detail}"
            case _:
                return self.detail or self.outcome.value


_HINTS: tuple[tuple[AttemptOutcome, str], ...] = (
    (
        AttemptOutcome.BAD_SIGNATURE,
        "An alias answered with a signature that does not verify. Either that host is "
        "not the service, or the key in the cached configuration is stale: log in "
        "again to fetch the current one.",
    ),
    (
        AttemptOutcome.UNSIGNED,
        "The instance pins an identity key, but a host answered without signing: it "
        "may run a version of the service that does not sign its challenge yet.",
    ),
    (
        AttemptOutcome.TLS,
        "A certificate was not accepted: pass an ssl_context that trusts the deployment's CA.",
    ),
    (
        AttemptOutcome.BAD_STATUS,
        "A host answered, but not as the service: it may still be starting, or "
        "something else listens there.",
    ),
    (
        AttemptOutcome.TIMEOUT,
        "Check that the service is running and that this machine is on a network it "
        "is reachable from.",
    ),
    (
        AttemptOutcome.UNREACHABLE,
        "Check that the service is running and that this machine is on a network it "
        "is reachable from.",
    ),
)


@dataclass(frozen=True)
class ServiceFailure:
    """Why one required (or optional) service has no working alias."""

    key: str
    service: str
    optional: bool
    instance: str | None = None
    """The granted instance's identifier, if one was granted."""
    attempts: tuple[AliasAttempt, ...] = ()
    reason: str | None = None
    """Set when it never came to a challenge (nothing granted, no aliases)."""

    def has(self, outcome: AttemptOutcome) -> bool:
        return any(attempt.outcome is outcome for attempt in self.attempts)

    def hint(self) -> str | None:
        """What to do about it, going by the gravest outcome."""
        return next((hint for outcome, hint in _HINTS if self.has(outcome)), None)

    def render(self) -> str:
        """The failure as text: one line per alias, the gravest first."""
        if self.reason is not None:
            return self.reason
        grave = AttemptOutcome.BAD_SIGNATURE
        attempts = sorted(self.attempts, key=lambda attempt: attempt.outcome is not grave)
        width = max(len(attempt.alias_id) for attempt in attempts)
        lines = [
            f"  - {attempt.alias_id:<{width}}  {attempt.url}  {attempt.describe()}"
            for attempt in attempts
        ]
        text = (
            f"All {len(attempts)} alias(es) of service {self.key} "
            f"(instance '{self.instance}') failed their challenge:\n" + "\n".join(lines)
        )
        if hint := self.hint():
            text += f"\n  {hint}"
        return text


class CompositionError(FaktsError):
    """Raised when required service instances could not be resolved

    This error is raised when one or more *required* services from the
    manifest could not be resolved to a working alias (no instance,
    no aliases, or all alias challenges failed). ``failures`` holds one
    :class:`ServiceFailure` per such service, with every alias that was
    tried and how its challenge ended.
    """

    def __init__(self, message: str, failures: tuple[ServiceFailure, ...] = ()) -> None:
        # Both to the base, so that the error survives a pickle.
        super().__init__(message, failures)
        self.failures = failures

    def __str__(self) -> str:
        return str(self.args[0])


class AliasNotFoundError(FaktsError):
    """Raised when no alias could be resolved for a requested service key

    This error is raised when the alias for a service key could not be
    resolved, e.g. because the service is not part of the manifest
    requirements, or all of its alias challenges failed.

    The special case of a *declared* requirement that was simply not
    granted by the server raises the subclass
    :class:`ServiceNotGrantedError` instead, so callers of optional
    services can degrade gracefully.
    """


class ServiceNotGrantedError(AliasNotFoundError):
    """Raised when a declared service requirement was not granted

    The service key *is* declared in the manifest requirements, but the
    server did not grant an instance for it — e.g. the user declined
    access to an optional service, or the deployment does not offer it.

    This is a subclass of :class:`AliasNotFoundError`, so existing
    handlers keep working. Catch this error specifically to distinguish
    "the user did not grant this optional service" (expected, degrade
    gracefully) from "the key is unknown or the service is unreachable"
    (likely a bug or an infrastructure problem).
    """


class ServiceUnreachableError(AliasNotFoundError):
    """Raised when a granted service has no alias that passes its challenge

    ``failure`` holds every alias that was tried and how its challenge
    ended. A subclass of :class:`AliasNotFoundError`, so existing handlers
    keep working.
    """

    def __init__(self, message: str, failure: ServiceFailure | None = None) -> None:
        # Both to the base, so that the error survives a pickle.
        super().__init__(message, failure)
        self.failure = failure

    def __str__(self) -> str:
        return str(self.args[0])


class NeedsReauthenticationError(FaktsError):
    """Raised when the session can only be recovered by a human.

    Refresh tokens do not live forever: servers cap both how long an
    individual token stays valid and how long a whole refresh chain may be
    renewed for. When either cap is reached — or the authorization was
    revoked, or superseded by a fresh approval elsewhere — there is nothing
    the client can do unattended.

    This is deliberately *not* handled by re-running the grant behind the
    user's back. An interactive grant opens a browser and causes the server
    to replace the app's client registration, which would kill every other
    process sharing the same credential. Catch this error and call
    :meth:`Fakts.alogin` at a moment when prompting is appropriate.
    """
