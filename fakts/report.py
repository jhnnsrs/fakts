"""Telling the server how alias resolution went (best effort).

Telemetry only: it never fails a lookup, never holds a lock, and never sends
the access token anywhere but the origin the app authenticated against.
"""

import logging
import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel

from fakts import oauth2
from fakts.models import ActiveFakts
from fakts.utils import truncate

logger = logging.getLogger(__name__)

REPORT_TIMEOUT = 5
"""Seconds to allow the alias report. Short on purpose: the lookup that
triggered it awaits it (after releasing its lock), and telemetry must not be
able to stall an app."""


class AliasReport(BaseModel):
    alias_id: str | None = None
    reason: str | None = None
    valid: bool = False


class ReportRequest(BaseModel):
    alias_reports: dict[str, AliasReport]
    functional: bool


@dataclass(frozen=True)
class PendingReport:
    """What one resolution found, waiting to be sent once the lock is released."""

    fakts: ActiveFakts
    report_map: dict[str, AliasReport]
    functional: bool
    token: str


def _same_origin(left: str, right: str) -> bool:
    """Whether two URLs share scheme, host and port."""
    a, b = urlparse(left), urlparse(right)
    return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)


async def areport_aliases(
    pending: PendingReport,
    *,
    ssl_context: ssl.SSLContext,
    allow_insecure_transport: bool,
) -> None:
    """Report the alias resolution outcome to the server (best effort).

    Reporting is telemetry and must never break the app: endpoints
    that do not advertise a report url are skipped, and any error
    during the report itself is caught and logged.

    The token is taken before resolution rather than fetched here: renewing
    can adopt another process's credential, which invalidates the aliases
    being reported on.
    """
    fakts, token = pending.fakts, pending.token
    if not fakts.auth.report_endpoint:
        logger.info("The endpoint does not advertise a report url. Skipping the alias report.")
        return

    # The report carries the access token, so it gets the same transport
    # gate as every other credential-bearing call — and must go to the
    # deployment we authenticated against. `report_endpoint` is derived
    # from a server-supplied base_url, so without the origin check a
    # misconfigured (or tampered) document would exfiltrate the bearer
    # token to an unrelated host.
    try:
        oauth2.check_transport(fakts.auth.report_endpoint, allow_insecure_transport)
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
        alias_reports=pending.report_map,
        functional=pending.functional,
    )
    logger.debug("Reporting usage: %s", report)

    try:
        async with (
            aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context),
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=aiohttp.ClientTimeout(total=REPORT_TIMEOUT),
            ) as session,
            session.post(
                fakts.auth.report_endpoint,
                json=report.model_dump(),
                # The bearer token must not follow a redirect elsewhere.
                allow_redirects=False,
            ) as resp,
        ):
            if resp.status != 200:
                body = await resp.text()
                logger.warning(
                    "Failed to report alias status to %s: status code %s. Response body: %s",
                    fakts.auth.report_endpoint,
                    resp.status,
                    truncate(body) or "<empty>",
                )
                return
            # The status is the answer; a body that is not JSON is no failure.
            logger.debug("Reported alias status to %s", fakts.auth.report_endpoint)
    except Exception:
        logger.warning(
            "Could not report alias status to %s. Continuing without reporting.",
            fakts.auth.report_endpoint,
            exc_info=True,
        )
