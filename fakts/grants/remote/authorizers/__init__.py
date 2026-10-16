"""Authorizers turn a discovered endpoint into a live OAuth2 session.

Each one drives a different grant at the same token endpoint: the device
code grant for interactive first-time approval, the mandate-key grant for
headless logins, and a plain refresh for a credential handed in from
outside.
"""

from .device_code import ClientKind, ClientRole, DeviceCodeAuthorizer
from .mandate_key import HeadlessClientKind, MandateKeyAuthorizer
from .static import StaticAuthorizer

__all__ = [
    "ClientKind",
    "ClientRole",
    "DeviceCodeAuthorizer",
    "HeadlessClientKind",
    "MandateKeyAuthorizer",
    "StaticAuthorizer",
]
