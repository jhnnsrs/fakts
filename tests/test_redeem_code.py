from dokker import Deployment
from fakts import Fakts
import os
from fakts.cache.nocache import NoCache
from fakts.grants.remote.base import RemoteGrant
from fakts.grants.remote.authorizers.redeem import RedeemAuthorizer
from fakts.grants.remote.discovery.well_known import WellKnownDiscovery
from fakts.models import Manifest, Requirement
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

    fakts = Fakts(
        grant=RemoteGrant(
            discovery=WellKnownDiscovery(
                url=f"http://localhost:{port_for_lok}",
            ),
            authorizer=RedeemAuthorizer(
                token="Y22joLbkjm4vtXMj_T4FD3U99Mb71pTFnUe-8KToAQI",
                manifest=manifest,
            ),
        ),
        cache=NoCache(),
        manifest=manifest,
    )
    with deployed_infra.create_watcher("lok") as watcher:
        with fakts:
            alias = fakts.get_alias("rekuest", omit_challenge=False)
            # The challenge should have resolved to the correct URL (which is reachable in the test environment)
            assert alias.challenge_path == "http://localhost:6888/ht"

            # The redeem flow should have claimed a fully-populated config
            # end to end: a usable auth block and the required instance.
            loaded = fakts.loaded_fakts
            assert loaded is not None
            assert loaded.auth.client_id
            assert loaded.auth.token_endpoint
            assert loaded.auth.refresh_token
            assert "rekuest" in loaded.instances
            assert loaded.instances["rekuest"].service == "live.arkitekt.rekuest"
