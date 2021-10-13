from abc import abstractmethod
from typing import Generic, Type, TypeVar
from pydantic.main import BaseModel
from fakts.beacon.beacon import FaktsEndpoint
import webbrowser
import asyncio
import uuid
from aiohttp import web
import aiohttp_cors
from urllib.parse import quote
from koil import koil

class RetrieverException(Exception):
    pass


class IncorrectStateException(Exception):
    pass



def wrapped_post_future(future, state):

    async def web_token_response(request):

        print(state) #TODO: Implement checking for state here
        future.set_result(await request.json())
        return web.json_response(data={"ok": True})

    return web_token_response

async def wait_for_post(starturl, redirect_host="localhost", redirect_port=6767, redirect_path = "/", timeout=400, print_function= False, handle_signals=False):
    

    state = uuid.uuid4()
    redirect_uri = quote(f"http://{redirect_host}:{redirect_port}{redirect_path}")

    webbrowser.open(starturl +f"?redirect_uri={redirect_uri}&state={state}")

    token_future = asyncio.get_event_loop().create_future()

    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={
    "*": aiohttp_cors.ResourceOptions(
            allow_headers="*",
        )
    })
    cors.add(app.router.add_post(redirect_path, wrapped_post_future(token_future, state)))


    webserver_task = asyncio.get_event_loop().create_task(web._run_app(app, host=redirect_host, port=redirect_port, print=print_function,handle_signals=handle_signals))
    done, pending = await asyncio.wait([token_future, webserver_task, asyncio.sleep(timeout)], return_when=asyncio.FIRST_COMPLETED)

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

    if not post_json: raise RetrieverException("No Post Data Received")
    return post_json


class FaktsRetriever:
    REDIRECT_HOST = "localhost"
    REDIRECT_PORT = 6767
    REDIRECT_PATH = "/"

    def __init__(self,*args, redirect_host= None, redirect_port = None, redirect_path = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.redirect_host = redirect_host or self.REDIRECT_HOST
        self.redirect_port = redirect_port or self.REDIRECT_PORT
        self.redirect_path = redirect_path or self.REDIRECT_PATH


    async def aretrieve(self, config: FaktsEndpoint, **kwargs):
        post_data = await wait_for_post(config.url, redirect_host=self.redirect_host, redirect_port=self.redirect_port, redirect_path=self.redirect_path)
        return post_data

    def retrieve(self, config, as_task=True, **kwargs):
        return koil(self.aretrieve(config, **kwargs), as_task=as_task)