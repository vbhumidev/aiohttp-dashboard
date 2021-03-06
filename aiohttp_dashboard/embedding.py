import aiohttp_jinja2
from jinja2 import FileSystemLoader
from aiohttp.web import WebSocketResponse, Response
from yarl import URL
from functools import partial
from os.path import join, normpath, isabs, dirname, abspath

from .core import Debugger, DEBUGGER_KEY, JINJA_KEY
from .event import HttpRequest, HttpResponse, WsMsgIncoming, WsMsgOutbound, MsgDirection


# these path fragments will be joined with `Debugger.path`
# websocket path for tranfer data messages
_URL_FRAGMENT_ENDPOINT = 'api'
# just path for serve static files
_URL_FRAGMENT_STATIC = 'static'
# path to static files location into file system
# see `Debugger._setup_routes`
_STATIC_PATH = join(dirname(abspath(__file__)), _URL_FRAGMENT_STATIC)


def setup(name, application, action_index, action_endpoint):
    application[DEBUGGER_KEY] = Debugger(name)

    _setup_routes(application, action_index, action_endpoint)
    _setup_static_routes(application)

    application.middlewares.append(_factory_on_request)
    application.on_response_prepare.append(_on_response)

    aiohttp_jinja2.setup(
        application,
        loader=FileSystemLoader(_STATIC_PATH),
        app_key=JINJA_KEY)

    return application


def _setup_routes(application, action_index, action_endpoint):
    debugger_path = application[DEBUGGER_KEY].path

    application.router.add_get(debugger_path, action_index)

    application.router.add_get(
        join(debugger_path, _URL_FRAGMENT_ENDPOINT), action_endpoint)


def _setup_static_routes(application):
    debugger_path = application[DEBUGGER_KEY].path

    application.router.add_static(
        join(debugger_path, _URL_FRAGMENT_STATIC), _STATIC_PATH)


async def _factory_on_request(application, handler):
    return partial(_on_request, handler=handler)


def _is_sutable_request(request):
    return not request.path.startswith(request.app[DEBUGGER_KEY].path)


async def _on_request(request, handler):
    if _is_sutable_request(request):
        request.app[DEBUGGER_KEY].register_request(request)

        try:
            return await handler(request)
        except Exception as exception:
            request.app[DEBUGGER_KEY].register_http_exception(request, exception)
            raise exception

    return await handler(request)


async def _on_response(request, response):
    if _is_sutable_request(request):
        request.app[DEBUGGER_KEY].register_response(request, response)

        if isinstance(response, WebSocketResponse):
            _ws_resposne_decorate(request, response)


def _on_websocket_msg(direction, request, message):
    if _is_sutable_request(request):
        request.app[DEBUGGER_KEY].register_websocket_message(
            direction, request, message)


def _ws_resposne_decorate(request, response):

    async def ping_decorator(message):
        _on_websocket_msg(MsgDirection.INCOMING, request, message)
        return await ping(message)

    ping, response.ping = response.ping, ping_decorator

    async def pong_decorator(message):
        _on_websocket_msg(MsgDirection.INCOMING, request, message)
        return await pong(message)

    pong, response.pong = response.pong, pong_decorator

    async def send_str_decorator(data, compress=None):
        _on_websocket_msg(MsgDirection.INCOMING, request, data)
        return await send_str(data, compress)

    send_str, response.send_str = response.send_str, send_str_decorator

    async def send_bytes_decorator(data, compress=None):
        _on_websocket_msg(MsgDirection.INCOMING, request, data)
        return await send_bytes(data, compress)

    send_bytes, response.send_bytes = response.send_bytes, send_bytes_decorator

    async def receive_decorator(timeout=None):
        message = await receive(timeout)
        _on_websocket_msg(MsgDirection.OUTBOUND, request, message.data)

        return message

    receive, response.receive = response.receive, receive_decorator


def endpoint_for_request(request):
    if request.secure:
        scheme = 'wss'
    else:
        scheme = 'ws'

    return URL.build(
        scheme=scheme,
        host=request.url.host,
        port=request.url.port,
        path=join(request.app[DEBUGGER_KEY].path, _URL_FRAGMENT_ENDPOINT),
    )
