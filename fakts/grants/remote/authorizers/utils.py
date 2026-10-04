import logging

logger = logging.getLogger(__name__)


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
