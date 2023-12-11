from fakts.grants.remote import RemoteGrant

from fakts.grants.remote.claimers.static import StaticClaimer
from fakts.grants.remote.discovery.static import StaticDiscovery
from fakts.grants.remote.demanders.static import StaticDemander
from fakts.grants.remote.types import FaktsEndpoint, FaktValue
from typing import Dict


def build_remote_testing(value: Dict[str, FaktValue]) -> RemoteGrant:
    """Builds a remote grant for testing purposes

    Will always return the same value when claiming.

    Parameters
    ----------
    value : Dict[str, FaktValue]
        The value to return when claiming

    Returns
    -------
    RemoteGrant
        The remote grant

    """
    return RemoteGrant(
        discovery=StaticDiscovery(
            endpoint=FaktsEndpoint(base_url="https://example.com")
        ),
        claimer=StaticClaimer(value=value),
        demander=StaticDemander(token="token"),  # type: ignore
    )
