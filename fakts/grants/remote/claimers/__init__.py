""" Remote Claimer mechanisms

This module contains the different cleaimer mechanisms
that can be used to retrieve a configuration from 
a previously discovered endpoint and its token.


These are NOT grants, but are used by the remote grant.

"""

from .static import StaticClaimer
from .post import ClaimEndpointClaimer

__all__ = ["StaticClaimer", "ClaimEndpointClaimer"]
