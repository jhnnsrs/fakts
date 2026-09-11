from fakts_next.grants.remote.models import FaktsEndpoint
import aiohttp
import logging
import ssl
from fakts_next.grants.remote.errors import DiscoveryError
from fakts_next.utils import truncate
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


async def check_wellknown(url: str, ssl_context: ssl.SSLContext, timeout: int = 4) -> FaktsEndpoint:
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

    Returns
    -------
    FaktsEndpoint
        A valid endpoint

    Raises
    ------
    DiscoveryError
    """
    url = f"{url}.well-known/fakts"

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_context),
        headers={"User-Agent": "Fakts/0.1", "Accept": "application/json"},
    ) as session:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
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
    auto_protocols: Optional[List[str]] = None,
    allow_appending_slash: bool = False,
    timeout: int = 4,
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

        errors: list[Tuple[str, Exception]] = []

        for protocol in auto_protocols:
            logger.info(f"Trying to connect to {protocol}://{url}")
            try:
                if allow_appending_slash and not url.endswith("/"):
                    url = f"{url}/"

                return await check_wellknown(f"{protocol}://{url}", ssl_context, timeout=timeout)
            except Exception as e:
                logger.info(f"Could not connect to {protocol}://{url}")
                errors.append((protocol, e))
                continue

        errors_string = "\n".join([f"- {protocol}://{url}\n  " + str(e) for protocol, e in errors])

        raise DiscoveryError(f"Could not connect via any protocol: \n{errors_string}")

    if allow_appending_slash and not url.endswith("/"):
        url = f"{url}/"

    return await check_wellknown(url, ssl_context, timeout=timeout)
