""" Remote Grants

Fakts remote grants are used to retrieve configuration from a remote endpoint. 
All this grants are based on the Fakts Registration Protocol that tries to ensure
legitmitate registration of apps on a dynamic endpoint



"""

from .retrieve import RetrieveGrant
from .static import StaticGrant
from .device_code import DeviceCodeGrant
from .base import RemoteGrant, Manifest

__all__ = ["RetrieveGrant", "StaticGrant", "DeviceCodeGrant", "RemoteGrant", "Manifest"]
