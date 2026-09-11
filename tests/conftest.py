"""Some configuration for pytest"""

from typing import Generator
import pytest
from dokker import Deployment, testing
import os

project_path = os.path.join(os.path.dirname(__file__), "integration")
docker_compose_file = os.path.join(project_path, "docker-compose.yml")


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
def deployed_infra() -> Generator[Deployment, None, None]:
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
