import asyncio
from http import HTTPStatus
import webbrowser
import aiohttp
import time
from pydantic import BaseModel, Field, model_validator
from fakts_next.grants.remote import FaktsEndpoint
from fakts_next.grants.remote.models import SSLContextModel
from fakts_next.grants.remote.errors import DemandError

from typing import Awaitable, Callable, List, Optional
from enum import Enum
from fakts_next.utils import truncate
from .utils import (
    print_device_code_prompt,
    print_succesfull_login,
)


DeviceCodeHook = Callable[["FaktsEndpoint", str], Awaitable[None]]
GrantedHook = Callable[["FaktsEndpoint", str], Awaitable[None]]


async def display_in_terminal(endpoint: "FaktsEndpoint", code: str) -> None:
    """The default device code hook: open the configure page in a browser
    and print the URL and code to the terminal."""
    # Prefer the configure page the server advertises; fall back to the
    # historical heuristic of deriving it from the base_url.
    base = endpoint.configure_url or endpoint.base_url.replace("lok/f/", "") + "configure/"
    if not base.endswith("/"):
        base += "/"
    device_url = base.replace("configure/", "device")

    webbrowser.open_new(base + code)

    print_device_code_prompt(
        base + code,
        device_url,
        code,
    )


async def granted_in_terminal(endpoint: "FaktsEndpoint", token: str) -> None:
    """A default hook that is called when the device code is granted"""
    print_succesfull_login()


class DeviceCodeError(DemandError):
    """A base class for all device code errors"""

    pass


class DeviceCodeTimeoutError(DeviceCodeError):
    """An error that is raised when the timeout for the device code grant is reached"""

    pass


class ClientKind(str, Enum):
    """The kind of client that you want to request"""

    DEVELOPMENT = "development"
    """Tries to set up a development client (client belongs to user)"""
    WEBSITE = "website"
    """Tries to set up a website client (allows for the client to be used by anyone)"""
    DESKTOP = "desktop"


class DeviceCodeDemander(SSLContextModel):
    """Device Code Grant

    The device code grant is a remote grant that is able to newly establish an application
    on the fakts_next server server that support the device code grant.

    When setting up the device code grant, the user will be prompted to visit a URL and enter a code.
    If open_browser is set to True, the URL will be opened in the default browser, and automatically
    entered. Otherwise the user will be prompted to enter the code manually.

    The device code grant will then poll the fakts_next server for the status of the code. If the code is
    still pending, the grant will wait for a second and then poll again. If the code is granted, the
    token will be returned. If the code is denied, an exception will be raised.

    """

    device_code_hook: DeviceCodeHook = Field(
        default=display_in_terminal,
        description="A callback function that is called when the device code is retrieved",
    )
    granted_hook: GrantedHook = Field(
        default=granted_in_terminal,
        description="A callback function that is called when the device code is granted",
    )

    manifest: BaseModel
    """ The manifest of the application that is requesting the token"""
    expiration_time_seconds: int = Field(
        default=300, description="The expiration time of the token in seconds"
    )
    """The expiration time of the token in seconds"""
    redirect_uris: List[str] = Field(
        default=[],
        description="The redirect uri to use for the client if it is a desktop application",
    )
    """The redirect uri to use for the client if it is a desktop application"""
    requested_client_kind: ClientKind = Field(
        ClientKind.DEVELOPMENT,
        description="The kind of client that you want to request",
    )
    """The kind of client that you want to request. Check the ClientKind enum for more information"""

    timeout: Optional[int] = None
    """The timeout for the device code grant in seconds. If the timeout is reached, the grant will fail.
    Defaults to expiration_time_seconds (giving up exactly when the code expires)."""

    open_browser: bool = True
    """If set to True, the URL will be opened in the default browser (if exists). Otherwise the user will be prompted to enter the code manually."""

    @model_validator(mode="after")
    def check_requested_matches_redirect_uris(
        self: "DeviceCodeDemander",
    ) -> "DeviceCodeDemander":  # type: ignore
        """Validates and checks that either a schema_dsl or schema_glob is provided, or that allow_introspection is set to True"""
        if not self.redirect_uris and self.requested_client_kind == ClientKind.WEBSITE:
            raise ValueError(
                "You must provide a redirect uri if you want to request a website client"
            )

        return self

    async def arequest_code(self, endpoint: FaktsEndpoint) -> str:
        """Requests a new code from the fakts_next server.

        This method will request a new code from the fakts_next server. This code will be used to
        authenticate the user. The user will be prompted to visit a URL and enter the code.

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to fetch the token for

        Returns
        -------
        str
            The devide-code that was requested
        """

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self.ssl_context)
        ) as session:
            async with session.post(
                f"{endpoint.base_url}start/",
                json={
                    "manifest": self.manifest.model_dump(),
                    "expiration_time_seconds": self.expiration_time_seconds,
                    "redirect_uris": self.redirect_uris,
                    "requested_client_kind": self.requested_client_kind,
                },
            ) as response:
                if response.status == HTTPStatus.OK:
                    result = await response.json()
                    if result["status"] == "granted":
                        return result["code"]

                    else:
                        raise DeviceCodeError(
                            f"The endpoint '{endpoint.name}' at {endpoint.base_url}start/ "
                            f"refused to start a device code flow for app "
                            f"'{getattr(self.manifest, 'identifier', 'unknown')}': "
                            f"{result.get('error', 'Unknown Error')}"
                        )

                else:
                    body = await response.text()
                    raise DeviceCodeError(
                        f"Could not start the device code flow at {endpoint.base_url}start/: "
                        f"status code {response.status}. "
                        f"Response body: {truncate(body) or '<empty>'}"
                    )

    async def ademand(self, endpoint: FaktsEndpoint) -> str:
        """Requests a token from the fakts_next server

        This method will request a token from the fakts_next server, using the device code grant.
        In the process, this grant will ask the fakts_next server to create a unique
        device code, it will then ask the user to visit a URL and enter the code.

        If open_browser is set to True, the URL will be opened in the default browser, and automatically
        entered. Otherwise the user will be prompted to enter the code manually.

        The device code grant will then poll the fakts_next server for the status of the code. If the code is
        still pending, the grant will wait for a second and then poll again. If the code is granted, the
        token will be returned. If the code is denied, an exception will be raised.

        Parameters
        ----------
        endpoint : FaktsEndpoint
            The endpoint to fetch the token for
        request : FaktsRequest
            The request to use for the fetching of the token

        Returns
        -------
        str


        """

        code = await self.arequest_code(endpoint)

        await self.device_code_hook(endpoint, code)

        timeout = self.timeout if self.timeout is not None else self.expiration_time_seconds
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
                        if result["status"] in ("waiting", "pending"):
                            if time.time() - start_time > timeout:
                                raise DeviceCodeTimeoutError(
                                    f"The device code '{code}' was not approved within "
                                    f"{timeout} seconds. Visit the configuration page of "
                                    f"'{endpoint.name}' and approve the code, or increase "
                                    f"the demander's timeout."
                                )

                            await asyncio.sleep(1)
                            continue

                        if result["status"] == "granted":
                            await self.granted_hook(endpoint, result["token"])
                            return result["token"]

                        if result["status"] == "error":
                            raise DeviceCodeError(
                                f"The endpoint '{endpoint.name}' at "
                                f"{endpoint.base_url}challenge/ reported an error for "
                                f"device code '{code}': "
                                f"{result.get('error', 'Unknown Error')}"
                            )

                        if result["status"] == "denied":
                            raise DeviceCodeError(
                                f"The user denied the device code request for app "
                                f"'{getattr(self.manifest, 'identifier', 'unknown')}' on "
                                f"'{endpoint.name}': "
                                f"{result.get('message', 'no message provided')}"
                            )

                    else:
                        body = await response.text()
                        raise DeviceCodeError(
                            f"Could not check the device code status at "
                            f"{endpoint.base_url}challenge/: status code {response.status}. "
                            f"Response body: {truncate(body) or '<empty>'}"
                        )
