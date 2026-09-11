from collections.abc import MutableMapping
from typing import Any, cast


def truncate(text: str, max_length: int = 300) -> str:
    """Truncate text for inclusion in an error message.

    Keeps error messages readable when quoting potentially large
    response bodies, while preserving enough of the payload to
    diagnose what the server actually answered.

    Parameters
    ----------
    text : str
        The text to truncate (e.g. an HTTP response body).
    max_length : int, optional
        The maximum number of characters to keep, by default 300.

    Returns
    -------
    str
        The (possibly truncated) text, with a note about how much
        was cut off.
    """
    text = text.strip()
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}... ({len(text) - max_length} more characters truncated)"


def update_nested(d: MutableMapping[str, Any], u: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Update a nested dictionary or similar mapping.
    This is a recursive function that will update the values in the dictionary
    *inplace*.

    Parameters
    ----------
    d : MutableMapping
        The dictionary to update.
    u : MutableMapping
        The dictionary to update from.

    Returns
    -------
    MutableMapping
        The updated dictionary (same as d).
    """
    for k, v in u.items():
        if isinstance(v, MutableMapping):
            d[k] = update_nested(d.get(k, {}), cast(MutableMapping[str, Any], v))
        else:
            d[k] = v
    return d
