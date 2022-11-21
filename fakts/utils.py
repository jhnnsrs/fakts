import collections.abc
from typing import Mapping


def update_nested(d: Mapping, u: Mapping) -> Mapping:
    """Update a nested dictionary or similar mapping.
    This is a recursive function that will update the values in the dictionary
    *inplace*.

    Args:
        d (Mapping): The dictionary to update
        u (Mapping): The dictionary to update with

    Returns:
        Mapping: The updated dictionary
    """
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = update_nested(d.get(k, {}), v)
        else:
            d[k] = v
    return d
