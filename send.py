import asyncio
from konfik.beacon import EndpointBeacon, KonfikEndpoint


beacon = EndpointBeacon(advertised_endpoints= [KonfikEndpoint(url="http://p-tnagerl-lab1:3000/setupapp", name="Best Man")])


async def main():

    task = await beacon.run()


asyncio.run(main())