from typing import List, Optional
from pydantic import Field
from fakts.discovery.base import Discovery
from fakts.discovery.static import StaticDiscovery
from fakts.grants.base import FaktsGrant


class RemoteGrant(FaktsGrant):
    timeout: int = Field(None, description="Timeout for the remote grant")
    discovery: Discovery = Field(default_factory=StaticDiscovery)
    scopes: List[str] = Field(default_factory=list)
    name: Optional[str] = None
