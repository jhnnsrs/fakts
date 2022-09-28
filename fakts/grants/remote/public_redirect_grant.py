import asyncio
from urllib.parse import urlencode
import uuid
import webbrowser
from fakts.grants.base import GrantException
import webbrowser
import asyncio
import uuid
from aiohttp import web
from urllib.parse import parse_qs, urlencode
from fakts.grants.remote.base import RemoteGrant
import json
import logging

logger = logging.getLogger(__name__)


class InvalidStateException(GrantException):
    pass


class NoConfigurationReceived(GrantException):
    pass


def wrapped_redirect_future(future: asyncio.Future, state: str):
    async def web_token_response(request):
        loop = asyncio.get_event_loop()
        logger.info("Received Reply from user")
        result = parse_qs(request.query_string)
        qs_state = result["state"][0]
        config = json.loads(result["config"][0])

        if qs_state != state:
            loop.call_soon_threadsafe(
                future.set_exception, InvalidStateException("Danger! Invalid State")
            )
            return web.Response(text="Error! Invalid State.")

        loop.call_soon_threadsafe(future.set_result, config)
        return web.Response(text="You can close me now !")

    return web_token_response


class PublicRedirectGrant(RemoteGrant):
    redirect_host = "localhost"
    redirect_port = 6767
    redirect_path = "/"

    async def aload(self, previous={}, **kwargs):

        endpoint = await self.discovery.discover()

        state = str(uuid.uuid4())

        params = {
            "state": state,
            "redirect_uri": f"http://{self.redirect_host}:{self.redirect_port}{self.redirect_path}",
            "name": self.name,
            "grant": "public_redirect",
            "scope": " ".join(self.scopes),
        }

        querystring = urlencode(
            {key: value for key, value in params.items() if value != None}
        )

        webbrowser.open_new(endpoint.base_url + "configure/?" + querystring)

        token_future = asyncio.get_event_loop().create_future()

        app = web.Application()

        app.router.add_get(
            self.redirect_path, wrapped_redirect_future(token_future, state)
        )

        webserver_task = asyncio.get_event_loop().create_task(
            web._run_app(
                app,
                host=self.redirect_host,
                port=self.redirect_port,
                print=False,
                handle_signals=False,
            )
        )
        logger.info(
            f"Waiting for redirect on {self.redirect_host}:{self.redirect_port}{self.redirect_path}"
        )

        done, pending = await asyncio.wait(
            [token_future, webserver_task],
            timeout=self.timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )

        for tf in done:
            if tf == token_future:
                post_json = tf.result()
            else:
                post_json = None

        for task in pending:
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

        if not post_json:
            raise NoConfigurationReceived("No Post Data Received")

        return post_json
