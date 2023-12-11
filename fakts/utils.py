from collections.abc import MutableMapping


def update_nested(d: MutableMapping, u: MutableMapping) -> MutableMapping:
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
            d[k] = update_nested(d.get(k, {}), v)
        else:
            d[k] = v
    return d
