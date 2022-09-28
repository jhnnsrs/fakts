from pydantic import Field
from fakts.discovery.base import Discovery
from fakts.discovery.qt.selectable_beacon import QtSelectableDiscovery
from fakts.grants.remote.qt.base import RemoteQtGrant


class RemoteSelectableQtGrant(RemoteQtGrant):
    discovery: Discovery = Field(default_factory=QtSelectableDiscovery)
