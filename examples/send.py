import asyncio
from fakts.beacon import EndpointBeacon, FaktsEndpoint


beacon = EndpointBeacon(
    advertised_endpoints=[
        FaktsEndpoint(url="http://p-tnagerl-lab1:3000/setupapp", name="Best Man")
    ]
)


async def main():
    await beacon.run()


asyncio.run(main())
