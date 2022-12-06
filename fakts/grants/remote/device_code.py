import asyncio
from http import HTTPStatus
from urllib.parse import urlencode
import uuid
import webbrowser
from fakts.grants.remote.base import RemoteGrant
import aiohttp
import time
from fakts.discovery.base import FaktsEndpoint
from typing import List
from pydantic import Field


def conditional_clipboard(text):
    try:
        import pyperclip

        pyperclip.copy(text)
    except ImportError:
        pass


try:
    from rich import print
    from rich.panel import Panel

    def print_device_code_prompt(url, code, scopes):
        conditional_clipboard(code)
        print(
            Panel.fit(
                f"""
        Please visit this URL to authorize this device:
        [bold green][link={url}]{url}[/link][/bold green]
        and enter the code:
        [bold blue]{code}[/bold blue]
        to grant the following scopes:
        [bold orange]{scopes}[/bold orange]
        """,
                title="Device Code Grant",
                title_align="center",
            )
        )

except ImportError:

    def print_device_code_prompt(url, code, scopes):
        conditional_clipboard(code)
        print("Please visit the following URL to complete the configuration:")
        print("\t" + url + "device")
        print("And enter the following code:")
        print("\t" + code)
        print("Make sure to select the following scopes")
        print("\t" + "\n\t".join(scopes))


class DeviceCodeGrant(RemoteGrant):
    """Device Code Grant

    The device code grant is a remote grant that is able to newly establish an application
    on the fakts server.
    Importantly this grant will genrate a new application on the fakts server, that
    is bound to ONE specific user. This means that this application will only be able to identifiy itself
    with the data of the user that granted the application in the first place (maps to the
    client-credentials grant in an oauth2 context).

    When setting up the device code grant, the user will be prompted to visit a URL and enter a code.
    If open_browser is set to True, the URL will be opened in the default browser, and automatically
    entered. Otherwise the user will be prompted to enter the code manually.

    The device code grant will then poll the fakts server for the status of the code. If the code is
    still pending, the grant will wait for a second and then poll again. If the code is granted, the
    token will be returned. If the code is denied, an exception will be raised.

    """

    scopes: List[str] = Field(default_factory=lambda: ["openid"])
    """ Scopes that this app should request from the user """

    timeout = 60
    """The timeout for the device code grant in seconds. If the timeout is reached, the grant will fail."""

    open_browser = True
    """If set to True, the URL will be opened in the default browser (if exists). Otherwise the user will be prompted to enter the code manually."""

    def generate_code(self):
        """Generates a random 6-digit alpha-numeric code"""

        return "".join([str(uuid.uuid4())[-1] for _ in range(6)])

    async def ademand(self, endpoint: FaktsEndpoint) -> str:
        """Requests a new token from the fakts server.

        This method will request a new token from the fakts server. If the token is not yet granted, the method will
        wait for a second and then poll again. If the token is granted, the token will be returned. If the token is
        denied, an exception will be raised.

        You can change the timeout of the grant by setting the timeout attribute.

        """

        code = self.generate_code()

        if self.open_browser:
            querystring = urlencode(
                {
                    "device_code": code,
                    "grant": "device_code",
                    "scope": " ".join(self.scopes),
                    "version": self.version,
                    "identifier": self.identifier,
                }
            )
            webbrowser.open_new(endpoint.base_url + "configure/?" + querystring)

        else:
            print_device_code_prompt(endpoint.base_url + "device", code, self.scopes)

        start_time = time.time()

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self.ssl_context)
        ) as session:
            while True:
                async with session.post(
                    f"{endpoint.base_url}challenge/", json={"code": code}
                ) as response:

                    if response.status == HTTPStatus.OK:
                        result = await response.json()
                        if result["status"] == "waiting":
                            if time.time() - start_time > self.timeout:
                                raise TimeoutError(
                                    "Timeout for device code grant reached."
                                )

                            await asyncio.sleep(1)
                            continue

                        if result["status"] == "pending":
                            if time.time() - start_time > self.timeout:
                                raise TimeoutError(
                                    "Timeout for device code grant reached."
                                )
                            await asyncio.sleep(1)
                            continue

                        if result["status"] == "granted":
                            return result["token"]

                    else:
                        raise Exception(
                            f"Error! Could not retrieve code {await response.text()}"
                        )