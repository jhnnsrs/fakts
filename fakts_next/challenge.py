"""Signed alias challenges.

When an instance carries a :class:`~fakts_next.models.ChallengeKey`, the
client sends a random nonce with each alias challenge and the service must
answer with a signature over a domain-separated message, made with the
matching private key. This proves the host answering the challenge actually
holds the service's identity key — a plain 200 from an impostor (or a
stale host) no longer passes.

The exact exchange (also documented in the README protocol section):

- request:  ``GET {challenge_path}?nonce=<nonce>``
- message:  ``UTF8("fakts-challenge-v1:" + nonce)``
- response: ``{"signature": "<base64(Ed25519-Sign(private_key, message))>"}``

The domain tag ensures a challenge signature can never be repurposed in
another protocol context (the service never signs raw client-supplied
bytes), and the fresh nonce prevents replay of recorded responses.

Note: without TLS, a signed challenge authenticates the *probe*, not the
connection — subsequent traffic can still be hijacked by an active
attacker relaying the probe. Use ssl aliases (ideally with the same key
pinned at the TLS layer) for full channel security.
"""

import base64
import logging
import secrets

from fakts_next.errors import FaktsError
from fakts_next.models import ChallengeKey

logger = logging.getLogger(__name__)

CHALLENGE_DOMAIN = "fakts-challenge-v1"
"""Domain separation tag prefixed to every signed challenge message"""


def generate_nonce() -> str:
    """Generate a fresh random nonce for a single challenge probe"""
    return secrets.token_urlsafe(24)


def build_challenge_message(nonce: str) -> bytes:
    """The exact bytes the service must sign for a given nonce"""
    return f"{CHALLENGE_DOMAIN}:{nonce}".encode()


def verify_challenge_signature(
    key: ChallengeKey, nonce: str, signature_b64: str
) -> bool:
    """Verify a signed challenge response against the pinned public key.

    Returns False on any mismatch (wrong key, wrong nonce, malformed
    base64). Raises FaktsError if the optional 'cryptography' dependency
    is missing — a pinned key must never silently downgrade to an
    unverified challenge.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as e:
        raise FaktsError(
            "The instance pins a challenge key, but the 'cryptography' package "
            "is not installed, so the signature cannot be verified. "
            "Install it with: pip install fakts-next[crypto]"
        ) from e

    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key.key))
    except Exception:
        logger.warning(
            "Could not parse the pinned challenge key. Failing the challenge.",
            exc_info=True,
        )
        return False

    try:
        public_key.verify(
            base64.b64decode(signature_b64), build_challenge_message(nonce)
        )
        return True
    except Exception:
        return False
