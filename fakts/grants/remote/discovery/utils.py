import logging
import ssl
from urllib.parse import urlparse

import aiohttp

from fakts.grants.remote.errors import DiscoveryError
from fakts.grants.remote.models import FaktsEndpoint
from fakts.oauth2 import client_session
from fakts.utils import truncate

logger = logging.getLogger(__name__)

#: The endpoints credentials are sent to. They must share the well-known
#: document's origin unless that is explicitly opted out of.
CREDENTIAL_ENDPOINTS = ("token_endpoint", "device_authorization_endpoint")


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    default = {"http": 80, "https": 443}.get(parsed.scheme)
    return parsed.scheme, (parsed.hostname or "").lower(), parsed.port or default


def _is_tls_failure(error: BaseException) -> bool:
    """Whether the server's certificate failed verification.

    That is an answer -- something is serving TLS there and it is not who it
    claims to be -- so it must not fall back to plain http. A protocol mismatch
    (https against a plain-http dev server, "wrong version number") may: the
    endpoints it yields are http, and credentials only go there when plain
    http was explicitly allowed (fakts.oauth2.check_transport).
    """
    return isinstance(
        error,
        (
            ssl.SSLCertVerificationError,
            aiohttp.ClientConnectorCertificateError,
            aiohttp.ServerFingerprintMismatch,
        ),
    )


async def check_wellknown(
    url: str,
    ssl_context: ssl.SSLContext,
    timeout: int = 4,
    allow_cross_origin_endpoints: bool = False,
) -> FaktsEndpoint:
    """Check the well-known endpoint

    This function will check the well-known endpoint and return the endpoint
    if it is valid. If it is not valid, it will raise an exception.

    Parameters
    ----------
    url : str
        Url to check
    ssl_context : ssl.SSLContext
        The ssl context to use for the connection
    timeout : int, optional
        The timeout for the connection , by default 4
    allow_cross_origin_endpoints : bool, optional
        Accept a token or device authorization endpoint on another origin than
        the well-known document. Off by default: a tampered document could
        otherwise send the credential flow anywhere.

    Returns
    -------
    FaktsEndpoint
        A valid endpoint

    Raises
    ------
    DiscoveryError
    """
    url = f"{url}.well-known/fakts"

    async with (
        client_session(
            ssl_context,
            timeout=timeout,
            headers={"User-Agent": "Fakts/0.1", "Accept": "application/json"},
        ) as session,
        session.get(url) as resp,
    ):
        if resp.status == 200:
            try:
                data = await resp.json()
            except Exception as e:
                body = await resp.text()
                raise DiscoveryError(
                    f"The well-known endpoint {url} answered with status 200, "
                    f"but the response is not valid JSON. Is a Fakts server "
                    f"really running at this address? "
                    f"Response body: {truncate(body) or '<empty>'}"
                ) from e

            if "name" not in data:
                logger.error(f"Malformed answer: {data}")
                raise DiscoveryError(
                    f"The well-known endpoint {url} answered, but the response "
                    f"is missing the required 'name' field. Is a Fakts server "
                    f"really running at this address? Received: {truncate(str(data))}"
                )

            # A v1 server omits protocol_version entirely. Name that
            # explicitly: a missing token_endpoint further down is a
            # baffling symptom for what is really a version mismatch.
            protocol_version = str(data.get("protocol_version", "1"))
            if protocol_version != "2":
                raise DiscoveryError(
                    f"{url} speaks fakts protocol version {protocol_version}, but "
                    f"fakts >= 5 requires version 2. The v2 protocol is an "
                    f"OAuth 2.0 extension and shares no endpoints with v1, so there "
                    f"is no compatibility mode. Upgrade the server, or pin "
                    f"fakts < 5 to keep talking to this one."
                )

            if not data.get("token_endpoint"):
                raise DiscoveryError(
                    f"{url} claims fakts protocol version 2 but advertises no "
                    f"'token_endpoint'. Received: {truncate(str(data))}"
                )

            if not allow_cross_origin_endpoints:
                for field in CREDENTIAL_ENDPOINTS:
                    endpoint_url = data.get(field)
                    if endpoint_url and _origin(endpoint_url) != _origin(url):
                        raise DiscoveryError(
                            f"{url} names its {field} on another origin: "
                            f"{endpoint_url}. Credentials are only sent to the origin "
                            f"that was discovered; if this deployment really splits "
                            f"its hosts, pass allow_cross_origin_endpoints=True."
                        )

            return FaktsEndpoint(**data)

        else:
            body = await resp.text()
            logger.error(f"Could not retrieve on the endpoint: {resp.status}")
            raise DiscoveryError(
                f"The well-known endpoint {url} answered with status code "
                f"{resp.status} (expected 200). Is the Fakts server running and "
                f"is the URL correct? Response body: {truncate(body) or '<empty>'}"
            )


async def discover_url(
    url: str,
    ssl_context: ssl.SSLContext,
    auto_protocols: list[str] | None = None,
    allow_appending_slash: bool = False,
    timeout: int = 4,
    allow_cross_origin_endpoints: bool = False,
) -> FaktsEndpoint:
    """Discover the endpoint from the url

    This function will try to discover the endpoint from the url. If the url
    does not contain a protocol, it will try to use the auto protocols to
    discover the endpoint.

    Parameters
    ----------
    url : str
        The (base) url to discover
    ssl_context : ssl.SSLContext
        The ssl context to use for the connection
    auto_protocols : Optional[List[str]], optional
        The protocols to try (e.g. http https), by default None
    allow_appending_slash : bool, optional
        Should we autoappend a slash if the ur does not conain it, by default False
    timeout : int, optional
        How long to wait to consider a connection not valid, by default 4

    Returns
    -------
    FaktsEndpoint
        The endpoint

    Raises
    ------
    DiscoveryError
    """

    if "://" not in url:
        logger.info(f"No protocol specified on {url}")
        if not auto_protocols or len(auto_protocols) == 0:
            raise DiscoveryError(
                f"The url '{url}' does not specify a protocol (e.g. 'https://{url}'), "
                f"and no auto_protocols are configured on the discovery to try instead."
            )

        errors: list[tuple[str, Exception]] = []

        for protocol in auto_protocols:
            logger.info(f"Trying to connect to {protocol}://{url}")
            try:
                if allow_appending_slash and not url.endswith("/"):
                    url = f"{url}/"

                return await check_wellknown(
                    f"{protocol}://{url}",
                    ssl_context,
                    timeout=timeout,
                    allow_cross_origin_endpoints=allow_cross_origin_endpoints,
                )
            except Exception as e:
                if _is_tls_failure(e):
                    # A failed certificate check is an answer, not an absence: falling
                    # back to plain http here is exactly what an attacker wants.
                    raise DiscoveryError(
                        f"TLS verification failed for {protocol}://{url}: {e}. Not "
                        f"falling back to another protocol. Fix the certificate (or "
                        f"the trusted CAs), or pass an explicit http:// URL."
                    ) from e
                logger.info(f"Could not connect to {protocol}://{url}")
                errors.append((protocol, e))
                continue

        errors_string = "\n".join([f"- {protocol}://{url}\n  " + str(e) for protocol, e in errors])

        raise DiscoveryError(f"Could not connect via any protocol: \n{errors_string}")

    if allow_appending_slash and not url.endswith("/"):
        url = f"{url}/"

    return await check_wellknown(
        url,
        ssl_context,
        timeout=timeout,
        allow_cross_origin_endpoints=allow_cross_origin_endpoints,
    )
