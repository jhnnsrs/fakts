import asyncio
from urllib.parse import urlencode
import uuid
import webbrowser
from pydantic import Field
import requests
from fakts.grants.remote.base import RemoteGrant


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
            print("Please visit the following URL to complete the configuration:")
            print("\t" + endpoint.base_url + "device")
            print("And enter the following code:")
            print("\t" + code)
            print("Make sure to select the following scopes")
            print("\t" + "\n\t".join(self.scopes))

        while True:
            answer = requests.post(
                f"{endpoint.base_url}challenge/", json={"code": code}
            )
            if answer.status_code == 200:
                nana = answer.json()
                if nana["status"] == "waiting":
                    await asyncio.sleep(1)
                    continue

                if nana["status"] == "pending":
                    await asyncio.sleep(1)
                    continue

                if nana["status"] == "granted":
                    return nana["config"]
            else:
                raise Exception("Error! Could not retrieve code")
