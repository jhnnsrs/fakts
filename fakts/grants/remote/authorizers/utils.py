import ipaddress
import logging
import os
import sys
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

QR_ENV = "FAKTS_QR"
"""``0`` never shows the approval link as a QR code, ``1`` always does; unset
leaves it to :func:`wants_qr`."""


def wants_qr(url: str, browser_opened: bool) -> bool:
    """Whether to show the approval link ``url`` as a QR code too.

    A QR code is for approving on another device -- a phone, when the app runs
    over SSH, in a container or on a shared instrument PC. So not when the page
    already opened here, and not for a loopback address no phone can reach.
    """
    setting = os.environ.get(QR_ENV, "").strip()
    if setting == "0":
        return False
    if setting == "1":
        return True
    if browser_opened:
        return False
    host = (urlparse(url).hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


_HALF_BLOCKS = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}


def qr_lines(url: str, light_ink: bool = False) -> list[str] | None:
    """``url`` as a QR code in half-block characters, two module rows per line,
    quiet zone included; ``None`` when segno is not installed.

    The glyphs draw the dark modules, for printing black on white -- whatever
    the terminal's theme, since a code inverted by a dark theme is one some
    scanners refuse. ``light_ink`` draws the light modules instead: for output
    that carries no colours, on the dark background most terminals have.
    """
    try:
        import segno  # pyright: ignore[reportMissingImports]
    except ImportError:
        logger.debug("Could not import segno, not showing a QR code")
        return None
    # make_qr, not make: a short link would otherwise become a Micro QR code,
    # which phone cameras do not read.
    rows = [[bool(module) != light_ink for module in row] for row in segno.make_qr(url, error="l").matrix_iter(border=2)]
    if len(rows) % 2:
        rows.append([light_ink] * len(rows[0]))
    return ["".join(_HALF_BLOCKS[pair] for pair in zip(top, bottom, strict=True)) for top, bottom in zip(rows[::2], rows[1::2], strict=True)]


def print_qr_code(url: str) -> None:
    """Print ``url`` as a QR code, black on white on a terminal; nothing when
    segno is not installed or the output cannot encode the glyphs."""
    stdout = sys.stdout
    coloured = stdout.isatty() and "NO_COLOR" not in os.environ
    lines = qr_lines(url, light_ink=not coloured)
    if not lines:
        return
    try:
        "".join(_HALF_BLOCKS.values()).encode(stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        return
    for line in lines:
        print(f"    \x1b[30;107m{line}\x1b[0m" if coloured else f"    {line}")


def could_copy_to_clipboard(text: str) -> bool:
    """Copies text to clipboard if possible

    This function tries to copy the text to the clipboard.
    If it fails, it returns False, otherwise True.

    Parameters
    ----------
    text : str
        The text to copy to the clipboard

    Returns
    -------
    bool
        Could the text be copied to the clipboard?
    """

    try:
        import pyperclip  # type: ignore[import]

        pyperclip.copy(text)
        return True
    except ImportError:
        logger.debug("Could not import pyperclip, not copying to clipboard")
        return False
    except Exception:
        # No clipboard backend (headless, no xclip): a convenience, never a
        # reason to abort the login.
        logger.debug("Could not copy to the clipboard", exc_info=True)
        return False


def _panel(text: str) -> bool:
    """Print ``text`` in a rich panel; ``False`` when rich is not installed.

    rich is imported here, when something is actually printed: a program that
    shows the login in its own interface never loads it.
    """
    try:
        from rich import print as rprint  # pyright: ignore[reportMissingImports]
        from rich.panel import Panel  # pyright: ignore[reportMissingImports]
    except ImportError:
        return False
    rprint(Panel.fit(text, title="Device Code Grant", title_align="center"))
    return True


def print_device_code_prompt(querystring: str, url: str, code: str) -> None:
    """Print the device code prompt, and copy the code to the clipboard if possible.

    Parameters
    ----------
    querystring : str
        The querystring to visit
    url : str
        The url to visit (without querystring)
    code : str
        The code to enter on the website
    """
    could_copy = could_copy_to_clipboard(code)
    if _panel(
        f"""
    Please visit the following URL:
    [bold green][link={querystring}]{querystring}[/link][/bold green]
    or go to this URL:
    [bold green][link={url}]{url}[/link][/bold green]
    and enter the code:
    [bold blue]{code}[/bold blue]
        """
    ):
        return
    print("Please visit the following URL:")
    print("\t" + querystring)
    print("Or go to this URL:")
    print("\t" + url)
    print("And enter the following code:")
    print("\t" + code)
    if could_copy:
        print("Code has been copied to clipboard")


def print_succesfull_login() -> None:
    """Print that the login went through."""
    if not _panel("You have successfully logged in!"):
        print("You have successfully logged in!")
