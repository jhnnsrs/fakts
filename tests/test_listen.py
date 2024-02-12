from fakts.grants.remote.discovery.advertised import alisten, ListenBinding
import asyncio
import pytest

async def listener():
    binding = ListenBinding(port=4234, magic_phrase="beacon-fakts")
    try:
        async for beacon in alisten(binding):
            print(beacon)
            break
    except asyncio.CancelledError as e:
        print("Cancelled")
        raise e


@pytest.mark.asyncio    
async def test_listener_cleanup():
    for i in range(10):
        task = asyncio.create_task(listener())

        await asyncio.sleep(i *0.1)

        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass


