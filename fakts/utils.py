from pydantic import ValidationError


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


def describe_validation_error(error: ValidationError) -> str:
    """Summarise a validation failure without echoing the input.

    What fakts validates is mostly credentials: a token response, the cache,
    ``$FAKTS``. pydantic's ``str(e)`` renders the offending values, so it would
    put (part of) a live refresh token into logs and tracebacks. Report only
    where each problem is and what kind it was.
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in problem['loc']) or '<root>'}: {problem['type']}"
        for problem in error.errors()
    )
