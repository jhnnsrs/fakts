from fakts.discovery.base import FaktsEndpoint
import aiohttp
import logging
import ssl
from fakts.discovery.errors import DiscoveryError
from typing import Optional, List

logger = logging.getLogger(__name__)

async def check_wellknown(url: str, ssl_context: ssl.SSLContext, timeout = 4) -> FaktsEndpoint:

    url = f"{url}.well-known/fakts"

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_context),
        headers={"User-Agent": "Fakts/0.1", "Accept": "application/json"},
    ) as session:
        async with session.get(
            url,
            timeout=timeout,
        ) as resp:

            if resp.status == 200:
                data = await resp.json()

                if "name" not in data:
                    logger.error(f"Malformed answer: {data}")
                    raise Exception("Malformed Answer")

                return FaktsEndpoint(**data)


            else:
                logger.error(f"Could not retrieve on the endpoint: {resp.status}")
                raise DiscoveryError(f"Error! We could not retrieve the endpoint. {url} ")



async def discover_url( url: str, ssl_context: ssl.SSLContext, auto_protocols: Optional[List[str]] = None, allow_appending_slash: bool = False, timeout= 4) -> FaktsEndpoint:
    


    if "://" not in url:
            logger.info(f"No protocol specified on {url}")
            if not auto_protocols or len(auto_protocols) == 0:
                raise DiscoveryError("No protocol specified and no auto protocols specified")
            
            errors = []
            
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