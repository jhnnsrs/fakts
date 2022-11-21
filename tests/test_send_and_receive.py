from fakts.discovery.beacon import advertise, retrieve_bindings
from fakts.discovery.base import FaktsEndpoint
import asyncio
from fakts.discovery.advertised import alisten, ListenBinding
import pytest


@pytest.mark.network
def test_can_retrieve_bindings():
    bindings = retrieve_bindings()
    assert len(bindings) > 0


@pytest.mark.network
async def test_advertise():

    bindings = retrieve_bindings()

    endpoint = FaktsEndpoint(
        name="test",
        base_url="http://localhost:8000/f/",
    )

    for binding in bindings:
        await advertise(binding, [endpoint], iterations=1)


@pytest.mark.network
async def test_adequate_canceling():

    bindings = retrieve_bindings()
    first_binding = bindings[0]

    endpoint = FaktsEndpoint(
        name="test",
        base_url="http://localhost:8000/f/",
    )

    advertise_task = asyncio.create_task(
        advertise(first_binding, [endpoint], iterations=-1)
    )
    await asyncio.sleep(0.1)
    advertise_task.cancel()

    try:
        await advertise_task
    except asyncio.CancelledError:
        pass

    await advertise(first_binding, [endpoint], iterations=1)


@pytest.mark.network
async def test_send_and_receive():
    bindings = retrieve_bindings()
    first_binding = bindings[0]

    endpoint = FaktsEndpoint(
        name="test",
        base_url="http://localhost:8000/f/",
    )

    advertise_task = asyncio.create_task(
        advertise(first_binding, [endpoint], iterations=-1)
    )
    await asyncio.sleep(0.1)

    async for p in alisten(ListenBinding()):
        assert p.name == "test"
        break

    advertise_task.cancel()

    try:
        await advertise_task
    except asyncio.CancelledError:
        pass
