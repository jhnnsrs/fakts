"""Remote Grants

Fakts remote grants retrieve configuration from a remote endpoint by
negotiating an OAuth 2.0 session with it: discover the server through its
well-known document, then run a grant (device code, redeem, or a plain
refresh) against its token endpoint.
"""

from .base import RemoteGrant
from .models import Authorizer, Discovery, FaktsEndpoint

__all__ = ["RemoteGrant", "Authorizer", "Discovery", "FaktsEndpoint"]
