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


try:
    # Optional: a nicer prompt when rich is installed.
    from rich import print as rprint  # pyright: ignore[reportMissingImports]
    from rich.panel import Panel  # pyright: ignore[reportMissingImports]

    def print_device_code_prompt(querystring: str, url: str, code: str) -> None:
        """Prints the device code prompt

        This function prints the device code prompt using rich.
        It also copies the code to the clipboard if possible.

        Parameters
        ----------
        querystring : str
            The querystring to visit
        url : str
            The url to visit (without querystring)
        code : str
            The code to enter on the website
        scopes : List[str]
            The scopes to grant
        """

        could_copy_to_clipboard(code)
        rprint(
            Panel.fit(
                f"""
    Please visit the following URL:
    [bold green][link={querystring}]{querystring}[/link][/bold green]
    or go to this URL:
    [bold green][link={url}]{url}[/link][/bold green]
    and enter the code:
    [bold blue]{code}[/bold blue]
        """,
                title="Device Code Grant",
                title_align="center",
            )
        )

    def print_succesfull_login() -> None:
        """Prints the successful login message

        This function prints the successful login message using rich.
        """
        rprint(
            Panel.fit(
                "You have successfully logged in!",
                title="Device Code Grant",
                title_align="center",
            )
        )

except ImportError:

    def print_device_code_prompt(querystring: str, url: str, code: str) -> None:
        """Prints the device code prompt

        This function prints the device code prompt using rich.
        It also copies the code to the clipboard if possible.

        Parameters
        ----------
        querystring : str
            The querystring to visit
        url : str
            The url to visit (without querystring)
        code : str
            The code to enter on the website
        scopes : List[str]
            The scopes to grant
        """
        could_copy = could_copy_to_clipboard(code)
        print("Please visit the following URL:")
        print("\t" + querystring)
        print("Or go to this URL:")
        print("\t" + url)
        print("And enter the following code:")
        print("\t" + code)
        if could_copy:
            print("Code has been copied to clipboard")

    def print_succesfull_login() -> None:
        """Prints the successful login message

        This function prints the successful login message using rich.
        """
        print("You have successfully logged in!")
