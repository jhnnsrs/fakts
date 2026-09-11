from dokker import Deployment
from fakts_next import Fakts
import os
from fakts_next.cache.nocache import NoCache
from fakts_next.grants.remote.base import RemoteGrant
from fakts_next.grants.remote.claimers import ClaimEndpointClaimer
from fakts_next.grants.remote.demanders.device_code import ClientKind, DeviceCodeDemander
from fakts_next.grants.remote.discovery.well_known import WellKnownDiscovery
from fakts_next.grants.remote.models import FaktsEndpoint
from fakts_next.models import Manifest, Requirement
import pytest

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))

@pytest.mark.integration
def test_device_code_grant(deployed_infra: Deployment):
    port_for_lok = deployed_infra.spec.find_service("lok").get_port_for_internal(80).published

    manifest = Manifest(
        version="0.1.0",
        identifier="test_manifest",
        scopes=["openid", "profile", "email"],
        requirements=[Requirement(key="rekuest", service="live.arkitekt.rekuest")],
    )

    async def authorize_through_cmd(endpoint: FaktsEndpoint, device_code: str) -> None:
        """Asynchronous function to authorize through command line."""
        

        await deployed_infra.arun(
            "lok", f"uv run python manage.py validatecode --code {device_code} --user demo --org demo --composition localhost"
        )

    fakts_next = Fakts(
        grant=RemoteGrant(
            discovery=WellKnownDiscovery(
                url=f"http://localhost:{port_for_lok}",
            ),
            demander=DeviceCodeDemander(
                device_code_hook=authorize_through_cmd,
                manifest=manifest,
                requested_client_kind=ClientKind.DEVELOPMENT,
            ),
            claimer=ClaimEndpointClaimer(),
        ),
        cache=NoCache(),
        manifest=manifest,
    )

    with fakts_next:
        alias = fakts_next.get_alias("rekuest", omit_challenge=False)
        # The challenge should have resolved to the correct URL (which is reachable in the test environment)
        assert alias.challenge_path == "http://localhost:6888/ht"