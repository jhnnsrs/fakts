"""Unit tests for the pure-logic utilities (``utils.py``) and the context
helpers (``helpers.py``)."""

from fakts.utils import truncate

# --------------------------------------------------------------------------- #
# utils.truncate
# --------------------------------------------------------------------------- #


def test_truncate_under_limit_passthrough():
    assert truncate("hello", max_length=300) == "hello"


def test_truncate_strips_whitespace():
    assert truncate("   hello   ") == "hello"


def test_truncate_empty_string():
    assert truncate("   ") == ""


def test_truncate_over_limit_adds_note():
    text = "a" * 350
    result = truncate(text, max_length=300)
    assert result.startswith("a" * 300)
    assert "50 more characters truncated" in result


# --------------------------------------------------------------------------- #
