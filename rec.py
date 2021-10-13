import asyncio
from konfik.beacon import KonfigBeacon, KonfikEndpoint
from konfik.discovery import EndpointDiscovery

async def w(endpoint):
    print(endpoint)


discov = EndpointDiscovery(on_new_endpoint=w)


async def main():

    task = await discov.scan()


asyncio.run(main())