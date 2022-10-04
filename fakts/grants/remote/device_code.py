import asyncio
from http import HTTPStatus
from urllib.parse import urlencode
import uuid
import webbrowser
from fakts.grants.remote.base import RemoteGrant
import aiohttp


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
    open_browser = True

    def generate_code(self):
        """Generates a random 6-digit alpha-numeric code"""

        return "".join([str(uuid.uuid4())[-1] for _ in range(6)])

    async def aload(self):

        endpoint = await self.discovery.discover()

        code = self.generate_code()

        if self.open_browser:
            querystring = urlencode(
                {
                    "device_code": code,
                    "grant": "device_code",
                    "scope": " ".join(self.scopes),
                    "name": self.name,
                }
            )
            webbrowser.open_new(endpoint.base_url + "configure/?" + querystring)

        else:
            print_device_code_prompt(endpoint.base_url + "device", code, self.scopes)

        async with aiohttp.ClientSession() as session:
            while True:
                async with session.post(
                    f"{endpoint.base_url}challenge/", json={"code": code}
                ) as response:

                    if response.status == HTTPStatus.OK:
                        result = await response.json()
                        if result["status"] == "waiting":
                            await asyncio.sleep(1)
                            continue

                        if result["status"] == "pending":
                            await asyncio.sleep(1)
                            continue

                        if result["status"] == "granted":
                            return result["config"]

                    else:
                        raise Exception("Error! Could not retrieve code")

        # while True:
        #     answer = requests.post(
        #         f"{endpoint.base_url}challenge/", json={"code": code}
        #     )
        #     if answer.status_code == 200:
        #         nana = answer.json()
        #         if nana["status"] == "waiting":
        #             await asyncio.sleep(1)
        #             continue

        #         if nana["status"] == "pending":
        #             await asyncio.sleep(1)
        #             continue

        #         if nana["status"] == "granted":
        #             return nana["config"]
        #     else:
        #         raise Exception("Error! Could not retrieve code")
