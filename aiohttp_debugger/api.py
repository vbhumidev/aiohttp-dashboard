from .debugger import (Debugger, WsMsgIncoming, WsMsgOutbound,
                       HttpRequest, HttpResponse, MsgDirection)
from .helper import casemethod
from operator import itemgetter
from asyncio import sleep, ensure_future, get_event_loop
from time import time
from collections import defaultdict
import warnings
import ujson


class Sender:

    def __init__(self, socket):
        self._socket = socket
        self._endpoints = defaultdict(lambda: None)

    def put(self, res_msg, req_msg):
        send_token = self._endpoints[req_msg.endpoint]

        if send_token is None:
            send_token = self._endpoints[req_msg.endpoint] = self.Proxy(
                handler=self._send)

            send_token.send_soon(args=(res_msg, req_msg))
        elif send_token.isoverdue:
            send_token.send_soon(args=(res_msg, req_msg))
        else:
            send_token.send_deferred(args=(res_msg, req_msg))

    def _send(self, res_msg, req_msg):
        if not self._socket.closed:
            self._socket.send_json(self._prepare_ws_response(res_msg, req_msg),
                dumps=ujson.dumps)
        else:
            warnings.warn('try send into closed websoclet connection')

    def _prepare_ws_response(self, res_msg, req_msg):
        return dict(data=res_msg, uid=req_msg.uid, endpoint=req_msg.endpoint)

    @property
    def id(self):
        return self._socket.id

    class Proxy:
        _delay = .4
        _handler = None
        _args = None
        _last_send_time = None
        _is_wait_for_call = False

        def __init__(self, handler):
            self._handler = handler

        def _handler_wrapper(self):
            self._handler(*self._args)
            self._is_wait_for_call = False
            self._last_send_time = time()

        def send_soon(self, args):
            self._args = args
            get_event_loop().call_soon(self._handler_wrapper)

        def send_deferred(self, args):
            self._args = args

            if not self._is_wait_for_call:
                self._is_wait_for_call = True
                get_event_loop().call_later(self._delay, self._handler_wrapper)

        @property
        def isoverdue(self):
            return (time() - self._last_send_time) > self._delay


class WsMsgDispatcherProxy:
    def __init__(self, dispatcher, sender):
        self._dispatcher = dispatcher
        self._sender = sender

    async def recive(self, req_msg):
        self._sender.put(await self._dispatcher.recive(req_msg), req_msg)

    def close(self):
        return self._dispatcher.close()


class WsMsgDispatcher:

    def __init__(self, sender):
        self._debugger = Debugger.instance
        self._sender = sender

    @casemethod
    def recive(req_msg):
        return req_msg.endpoint

    @recive.case('sibsribe.request')
    async def recive(self, req_msg):
        rid = int(req_msg.data['id'])

        def response():
            return dict(item=self._debugger.api.request(rid))

        def on(event):
            if event.rid == rid:
                self._send(response(), req_msg)

        self._debugger.on(HttpRequest, on, group=self._sender.id, hid=req_msg.uid)
        self._debugger.on(HttpResponse, on, group=self._sender.id, hid=req_msg.uid)

        return response()

    @recive.case('sibsribe.request.messages')
    async def recive(self, req_msg):
        rid = int(req_msg.data['id'])
        page = int(req_msg.data['page'])
        perpage = int(req_msg.data['perpage'])

        def res_msg():
            return dict(
                collection=self._debugger.api.messages(rid, page, perpage),
                total=self._debugger.api.count_by_direction(rid),
                incoming=self._debugger.api.count_by_direction(rid, MsgDirection.INCOMING),
                outbound=self._debugger.api.count_by_direction(rid, MsgDirection.OUTBOUND)
            )

        def on(event: WsMsgIncoming or WsMsgOutbound):
            if event.rid == rid:
                self._send(res_msg(), req_msg)

        self._debugger.on(WsMsgIncoming, on, group=self._sender.id, hid=req_msg.uid)
        self._debugger.on(WsMsgOutbound, on, group=self._sender.id, hid=req_msg.uid)

        return res_msg()

    @recive.case('sibsribe.requests')
    async def recive(self, req_msg):

        def res_msg():
            return self._debugger.api.requests()

        def on(event):
            self._send(res_msg(), req_msg)

        self._debugger.on(HttpRequest, on, group=self._sender.id, hid=req_msg.uid)
        self._debugger.on(HttpResponse, on, group=self._sender.id, hid=req_msg.uid)

        return res_msg()

    @recive.case('unsibscribe')
    async def recive(self, req_msg):
        """ with this hid maybe be multiple handlers """
        self._debugger.off(hid=req_msg.data['id'])

    @recive.case('fetch.info')
    async def recive(self, req_msg):
        return self._debugger.api.platform_info()

    @recive.default
    async def recive(self, req_msg):
        return {"status": "endpoint not found"}

    @recive.catch(Exception)
    async def recive(self, exception):
        """ TODO - async eception not catch through this way """
        return {"status": "error", "cause": str(exception)}

    def close(self):
        self._debugger.off(group=self._sender.id)

    def _send(self, res_msg, req_msg):
        self._sender.put(res_msg, req_msg)