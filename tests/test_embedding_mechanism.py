from os.path import join
import aiohttp.web
import aiohttp_debugger
from aiohttp_debugger import action
from aiohttp_debugger.debugger import DEBUGGER_KEY
from aiohttp_debugger.embedding import _factory_on_request, _on_response


def empty_application(prefix):
    return aiohttp_debugger.setup(prefix, aiohttp.web.Application())


def test_debugger(prefix):
    """ Test for registration Debugger in application """

    assert DEBUGGER_KEY in empty_application(prefix).keys()


def test_middlewares(prefix):
    """ Test for registration middlewares in application """

    application = empty_application(prefix)
    assert _factory_on_request in application.middlewares


def test_signals(prefix):
    """ Test for registration signals in application """

    application = empty_application(prefix)
    assert _on_response in application.on_response_prepare

