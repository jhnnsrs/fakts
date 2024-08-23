""" Remote Discovery mechanisms

This module contains the different discovery mechanisms
that can be used to discover the endpoint to connect to.

These are NOT grants, and are used by the remote grants
to discover the endpoint to connect to.

"""

from .static import StaticDiscovery
from .well_known import WellKnownDiscovery
from .advertised import FirstAdvertisedDiscovery

__all__ = ["StaticDiscovery", "FirstAdvertisedDiscovery", "WellKnownDiscovery"]
