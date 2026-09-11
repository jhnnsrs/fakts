from dokker import Deployment
from fakts import Fakts
import os
from fakts.cache.nocache import NoCache
from fakts.grants.remote.base import RemoteGrant
from fakts.grants.remote.authorizers.device_code import (
    ClientKind,
    DeviceCodeAuthorizer,
)
from fakts.grants.remote.discovery.well_known import WellKnownDiscovery
from fakts.grants.remote.models import FaktsEndpoint
from fakts.models import Manifest, Requirement
import pytest

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))

@pytest.mark.integration
def test_device_code_grant_node_id(deployed_infra: Deployment):
    port_for_lok = deployed_infra.spec.find_service("lok").get_port_for_internal(80).published

    manifest = Manifest(
        version="0.1.0",
        identifier="test_manifest",
        scopes=["openid", "profile", "email"],
        requirements=[Requirement(key="rekuest", service="live.arkitekt.rekuest")],
        node_id="test_node",
    )

    async def authorize_through_cmd(endpoint: FaktsEndpoint, device_code: str) -> None:
        """Approve the staged device code out of band, standing in for a user.

        The hook receives the *user* code — the short one a person would type
        on the approval page — which is what the server looks the pending
        registration up by.
        """
        

        await deployed_infra.arun(
            "lok", f"uv run python manage.py validatecode --code {device_code} --user demo --org demo --hub localhost"
        )

    fakts = Fakts(
        grant=RemoteGrant(
            discovery=WellKnownDiscovery(
                url=f"http://localhost:{port_for_lok}",
            ),
            authorizer=DeviceCodeAuthorizer(
                device_code_hook=authorize_through_cmd,
                manifest=manifest,
                requested_client_kind=ClientKind.DEVELOPMENT,
                open_browser=False,
            ),
        ),
        cache=NoCache(),
        manifest=manifest,
    )

    with fakts:
        alias = fakts.get_alias("rekuest", omit_challenge=False)
        # The challenge should have resolved to the correct URL (which is reachable in the test environment)
        port_for_rekuest = (
            deployed_infra.spec.find_service("rekuest").get_port_for_internal(80).published
        )
        assert alias.challenge_path == f"http://localhost:{port_for_rekuest}/ht"