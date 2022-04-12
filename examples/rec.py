import asyncio
from fakts.beacon import EndpointDiscovery

async def w(endpoint):
    print(endpoint)


discov = EndpointDiscovery(on_new_endpoint=w)


async def main():

    task = await discov.scan()


asyncio.run(main())