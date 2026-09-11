"""Some configuration for pytest"""

import os
import socket
import tempfile
from pathlib import Path
from typing import Generator, Iterator

import pytest
from dokker import Deployment, testing

project_path = os.path.join(os.path.dirname(__file__), "integration")
docker_compose_file = os.path.join(project_path, "docker-compose.yml")
lok_config_template = os.path.join(project_path, "configs", "lok.yaml")


def _reserve_free_ports(count: int) -> list[int]:
    """Ask the OS for `count` distinct free TCP ports.

    All sockets are held open until every port has been assigned, so the
    kernel cannot hand out the same port twice within one call. They are
    released before compose binds them -- a race in theory, but the ephemeral
    range is large and this is what keeps concurrent runs (and the leftovers
    of a crashed one) from colliding on a fixed port.
    """
    sockets: list[socket.socket] = []
    try:
        for _ in range(count):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [int(sock.getsockname()[1]) for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


@pytest.fixture(scope="session")
def integration_ports() -> Iterator[dict[str, int]]:
    """Pick this run's host ports and point compose at them.

    `lok.yaml` advertises rekuest's address to the client, which then
    challenges it for real, so the port has to be baked into the config
    *before* the stack comes up -- that is why the ports are reserved here
    rather than letting docker assign them and reading them back afterwards.
    The rendered config is written to a temp file and mounted in place of the
    tracked template, which keeps the checked-in file free of run-specific
    values.
    """
    lok_port, rekuest_port, minio_port = _reserve_free_ports(3)

    template = Path(lok_config_template).read_text()
    assert "__REKUEST_HOST_PORT__" in template, (
        "lok.yaml lost its __REKUEST_HOST_PORT__ placeholder; the client would "
        "be handed an address that nothing is listening on."
    )
    rendered = template.replace("__REKUEST_HOST_PORT__", str(rekuest_port))

    with tempfile.TemporaryDirectory(prefix="fakts-integration-") as tmpdir:
        # Readable by the docker daemon, which mounts it into the container.
        os.chmod(tmpdir, 0o755)
        config_file = Path(tmpdir) / "lok.yaml"
        config_file.write_text(rendered)
        config_file.chmod(0o644)

        env = {
            "LOK_HOST_PORT": str(lok_port),
            "REKUEST_HOST_PORT": str(rekuest_port),
            "MINIO_HOST_PORT": str(minio_port),
            "LOK_CONFIG_FILE": str(config_file),
        }
        previous = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        try:
            yield {"lok": lok_port, "rekuest": rekuest_port, "minio": minio_port}
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


async def token_loader() -> str:
    """Asynchronous function to load a token for authentication.

    This returns the "test" token which is configured as a static token to map to
    the user "test" in the test environment. In a real application, this function
    will return an oauth2 token or similar authentication token.

    To change this mapping you can alter the static_token configuration in the
    mikro configuration file (inside the integration folder).

    """
    return "test"


@pytest.fixture(scope="session")
def deployed_infra(integration_ports: dict[str, int]) -> Generator[Deployment, None, None]:
    """Fixture to deploy the Fakts server application with Docker Compose.

    This fixture sets up the Fakts server application using Docker Compose,
    configures health checks, and provides a deployed instance of Fakts
    for testing purposes. It also includes watchers for the Fakts and MinIO
    services to monitor their logs, when performing requests against the application.

    Yields:
        Deployment: The deployed instance of the Fakts server application.
    """
    setup = testing(docker_compose_file)
    # Configure the Fakts instance
    setup.add_health_check(
        url=lambda spec: (
            f"http://localhost:{spec.find_service('lok').get_port_for_internal(80).published}/ht"
        ),
        service="lok",
        timeout=5,
        max_retries=10,
    )
    setup.add_health_check(
        url=lambda spec: (
            f"http://localhost:{spec.find_service('rekuest').get_port_for_internal(80).published}/ht"
        ),
        service="rekuest",
        timeout=5,
        max_retries=10,
    )

    with setup as deployed:
        setup.down()

        setup.pull()

        setup.up()

        setup.check_health()
        yield deployed
