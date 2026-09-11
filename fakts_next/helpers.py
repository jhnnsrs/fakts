from fakts_next.fakts import get_current_fakts_next
from fakts_next.models import Alias
from koil.bridge import unkoil


async def afakt(key: str, omit_challenge: bool = False) -> Alias:
    """Asynchronous helper function to retrieve an Alias from the current Fakts instance."""
    value = await get_current_fakts_next().aget_alias(
        key, omit_challenge=omit_challenge
    )
    return value


def fakt(key: str, omit_challenge: bool = False) -> Alias:
    """Helper function to retrieve an Alias from the current Fakts instance. (will cause the whole call stack to be synchronous, so only use in tests or when you are sure it won't cause issues)"""
    return unkoil(afakt, key, omit_challenge=omit_challenge)
