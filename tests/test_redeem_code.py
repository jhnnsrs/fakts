from dokker import Deployment
from fakts_next import Fakts
import os
from fakts_next.cache.nocache import NoCache
from fakts_next.grants.remote.base import RemoteGrant
from fakts_next.grants.remote.claimers import ClaimEndpointClaimer
from fakts_next.grants.remote.demanders.redeem import RedeemDemander
from fakts_next.grants.remote.discovery.well_known import WellKnownDiscovery
from fakts_next.models import Manifest, Requirement
import pytest

TESTS_FOLDER = str(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.integration
def test_redeem_code_grant(deployed_infra: Deployment):
    port_for_lok = (
        deployed_infra.spec.find_service("lok").get_port_for_internal(80).published
    )

    manifest = Manifest(
        version="0.1.0",
        identifier="test_manifest",
        scopes=["openid", "profile", "email"],
        requirements=[Requirement(key="rekuest", service="live.arkitekt.rekuest")],
    )

    fakts_next = Fakts(
        grant=RemoteGrant(
            discovery=WellKnownDiscovery(
                url=f"http://localhost:{port_for_lok}",
            ),
            demander=RedeemDemander(
                token="Y22joLbkjm4vtXMj_T4FD3U99Mb71pTFnUe-8KToAQI",
                manifest=manifest,
            ),
            claimer=ClaimEndpointClaimer(),
        ),
        cache=NoCache(),
        manifest=manifest,
    )
    with deployed_infra.create_watcher("lok") as watcher:
        with fakts_next:
            alias = fakts_next.get_alias("rekuest", omit_challenge=False)
            # The challenge should have resolved to the correct URL (which is reachable in the test environment)
            assert alias.challenge_path == "http://localhost:6888/ht"

            # The redeem flow should have claimed a fully-populated config
            # end to end: a usable auth block and the required instance.
            loaded = fakts_next.loaded_fakts
            assert loaded is not None
            assert loaded.auth.client_id
            assert loaded.auth.token_url
            assert "rekuest" in loaded.instances
            assert loaded.instances["rekuest"].service == "live.arkitekt.rekuest"
