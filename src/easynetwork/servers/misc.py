# Copyright 2021-2026, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Server implementation tools module."""

from __future__ import annotations

__all__ = [
    "build_lowlevel_blocking_datagram_server_handler",
    "build_lowlevel_blocking_stream_server_handler",
    "build_lowlevel_datagram_server_handler",
    "build_lowlevel_stream_server_handler",
]

import inspect
import logging
from collections.abc import AsyncGenerator, Callable, Generator, Hashable
from contextlib import AbstractAsyncContextManager, AbstractContextManager, AsyncExitStack, ExitStack

from ..lowlevel import _utils
from ..lowlevel.api_async.servers import datagram as _async_datagram_server, stream as _async_stream_server
from ..lowlevel.api_sync.servers import selector_datagram as _blocking_datagram_server, selector_stream as _blocking_stream_server
from ..lowlevel.request_handler import RecvParams
from .handlers import (
    AsyncDatagramClient,
    AsyncDatagramRequestHandler,
    AsyncStreamClient,
    AsyncStreamRequestHandler,
    BlockingDatagramClient,
    BlockingDatagramRequestHandler,
    BlockingStreamClient,
    BlockingStreamRequestHandler,
)


def build_lowlevel_stream_server_handler[*VarArgs, Request, Response](
    initializer: Callable[
        [_async_stream_server.ConnectedStreamClient[Response], *VarArgs],
        AbstractAsyncContextManager[AsyncStreamClient[Response] | None],
    ],
    request_handler: AsyncStreamRequestHandler[Request, Response],
    *args: *VarArgs,
    logger: logging.Logger | None = None,
) -> Callable[[_async_stream_server.ConnectedStreamClient[Response]], AsyncGenerator[RecvParams | None, Request]]:
    """
    Creates an :term:`asynchronous generator` function, usable by :meth:`.AsyncStreamServer.serve`, from
    an :class:`.AsyncStreamRequestHandler`.

    .. versionchanged:: 1.1
        Added variadic arguments for `initializer`.

    Parameters:
        initializer: a callback returning an :term:`asynchronous context manager` to create the final client interface and
                     set up the request handler generator.
                     The yielded value can be :data:`None` if the initializer failed silently.
        request_handler: the high-level interface which handles the incoming requests.
        logger: if given, will be used to log some warnings.

    Returns:
        an :term:`asynchronous generator` function.
    """

    if logger is None:
        logger = logging.getLogger(__name__)

    from ..lowlevel.api_async.transports import utils as _transports_utils

    async def handler(
        lowlevel_client: _async_stream_server.ConnectedStreamClient[Response], /
    ) -> AsyncGenerator[RecvParams | None, Request]:
        async with initializer(lowlevel_client, *args) as client, AsyncExitStack() as request_handler_exit_stack:
            del lowlevel_client

            if client is None:
                # Initialization failed, but must not raise an exception.
                return

            request_handler_generator: AsyncGenerator[RecvParams | None, Request]
            request: Request | None
            recv_params: RecvParams | None

            _on_connection_hook = request_handler.on_connection(client)
            if isinstance(_on_connection_hook, AsyncGenerator):
                try:
                    recv_params = await anext(_on_connection_hook)
                except StopAsyncIteration:
                    pass
                else:
                    while True:
                        try:
                            try:
                                request = yield recv_params
                            except GeneratorExit:  # pragma: no cover
                                raise
                            except BaseException as exc:
                                del recv_params
                                recv_params = await _on_connection_hook.athrow(exc)
                            else:
                                del recv_params
                                recv_params = await _on_connection_hook.asend(request)
                            finally:
                                request = None
                        except StopAsyncIteration:
                            break
                        except BaseException as exc:
                            # Remove asend()/athrow() frame
                            _utils.remove_traceback_frames_in_place(exc, 1)
                            raise
                finally:
                    await _on_connection_hook.aclose()
            else:
                assert inspect.isawaitable(_on_connection_hook)  # nosec assert_used
                await _on_connection_hook
            del _on_connection_hook

            async def disconnect_client() -> None:
                try:
                    await request_handler.on_disconnection(client)
                except* ConnectionError:
                    logger.warning("ConnectionError raised in request_handler.on_disconnection()")

            request_handler_exit_stack.push_async_callback(disconnect_client)

            del request_handler_exit_stack

            new_request_handler = request_handler.handle
            client_is_closing = client.is_closing

            while not client_is_closing():
                request_handler_generator = new_request_handler(client)
                try:
                    recv_params = await anext(request_handler_generator)
                except StopAsyncIteration:
                    await _transports_utils.aclose_forcefully(client)
                    return
                else:
                    while True:
                        try:
                            try:
                                request = yield recv_params
                            except GeneratorExit:  # pragma: no cover
                                raise
                            except BaseException as exc:
                                del recv_params
                                recv_params = await request_handler_generator.athrow(exc)
                            else:
                                del recv_params
                                recv_params = await request_handler_generator.asend(request)
                            finally:
                                request = None
                        except StopAsyncIteration:
                            break
                        except BaseException as exc:
                            # Remove asend()/athrow() frame
                            _utils.remove_traceback_frames_in_place(exc, 1)
                            raise
                finally:
                    await request_handler_generator.aclose()

    return handler


def build_lowlevel_datagram_server_handler[*VarArgs, Request, Response, Address: Hashable](
    initializer: Callable[
        [_async_datagram_server.DatagramClientContext[Response, Address], *VarArgs],
        AbstractAsyncContextManager[AsyncDatagramClient[Response] | None],
    ],
    request_handler: AsyncDatagramRequestHandler[Request, Response],
    *args: *VarArgs,
) -> Callable[[_async_datagram_server.DatagramClientContext[Response, Address]], AsyncGenerator[RecvParams | None, Request]]:
    """
    Creates an :term:`asynchronous generator` function, usable by :meth:`.AsyncDatagramServer.serve`, from
    an :class:`.AsyncDatagramRequestHandler`.

    .. versionchanged:: 1.1
        Added variadic arguments for `initializer`.

    Parameters:
        initializer: a callback returning an :term:`asynchronous context manager` to create the final client interface and
                     set up the request handler generator.
                     The yielded value can be :data:`None` if the initializer failed silently.
        request_handler: the high-level interface which handles the incoming requests.

    Returns:
        an :term:`asynchronous generator` function.
    """

    async def handler(
        lowlevel_client: _async_datagram_server.DatagramClientContext[Response, Address], /
    ) -> AsyncGenerator[RecvParams | None, Request]:
        async with initializer(lowlevel_client, *args) as client:
            del lowlevel_client

            if client is None:
                # Initialization failed, but must not raise an exception.
                return

            request_handler_generator = request_handler.handle(client)
            request: Request | None
            recv_params: RecvParams | None
            try:
                recv_params = await anext(request_handler_generator)
            except StopAsyncIteration:
                return
            else:
                while True:
                    try:
                        try:
                            request = yield recv_params
                        except GeneratorExit:  # pragma: no cover
                            raise
                        except BaseException as exc:
                            del recv_params
                            recv_params = await request_handler_generator.athrow(exc)
                        else:
                            del recv_params
                            recv_params = await request_handler_generator.asend(request)
                        finally:
                            request = None
                    except StopAsyncIteration:
                        return
                    except BaseException as exc:
                        # Remove asend()/athrow() frame
                        _utils.remove_traceback_frames_in_place(exc, 1)
                        raise
            finally:
                await request_handler_generator.aclose()

    return handler


def build_lowlevel_blocking_stream_server_handler[*VarArgs, Request, Response](
    initializer: Callable[
        [_blocking_stream_server.ConnectedStreamClient[Response], *VarArgs],
        AbstractContextManager[BlockingStreamClient[Response] | None],
    ],
    request_handler: BlockingStreamRequestHandler[Request, Response],
    *args: *VarArgs,
    logger: logging.Logger | None = None,
) -> Callable[[_blocking_stream_server.ConnectedStreamClient[Response]], Generator[RecvParams | None, Request]]:
    """
    Creates a :term:`generator` function, usable by :meth:`.SelectorStreamServer.serve`, from
    a :class:`.BlockingStreamRequestHandler`.

    .. versionadded:: NEXT_VERSION

    Parameters:
        initializer: a callback returning a :term:`context manager` to create the final client interface and
                     set up the request handler generator.
                     The yielded value can be :data:`None` if the initializer failed silently.
        request_handler: the high-level interface which handles the incoming requests.
        logger: if given, will be used to log some warnings.

    Returns:
        a :term:`generator` function.
    """

    if logger is None:
        logger = logging.getLogger(__name__)

    def handler(
        lowlevel_client: _blocking_stream_server.ConnectedStreamClient[Response], /
    ) -> Generator[RecvParams | None, Request]:
        with initializer(lowlevel_client, *args) as client, ExitStack() as request_handler_exit_stack:
            del lowlevel_client

            if client is None:
                # Initialization failed, but must not raise an exception.
                return

            request_handler_generator: Generator[RecvParams | None, Request]
            request: Request | None
            recv_params: RecvParams | None

            match request_handler.on_connection(client):
                case None:
                    pass
                case Generator() as request_handler_generator:
                    yield from request_handler_generator

            def disconnect_client() -> None:
                try:
                    request_handler.on_disconnection(client)
                except* ConnectionError:
                    logger.warning("ConnectionError raised in request_handler.on_disconnection()")

            request_handler_exit_stack.callback(disconnect_client)

            del request_handler_exit_stack

            new_request_handler = request_handler.handle
            client_is_closing = client.is_closing

            while not client_is_closing():
                request_handler_generator = new_request_handler(client)
                try:
                    recv_params = next(request_handler_generator)
                except StopAsyncIteration:
                    client.abort()
                    return
                else:
                    while True:
                        try:
                            try:
                                request = yield recv_params
                            except GeneratorExit:  # pragma: no cover
                                raise
                            except BaseException as exc:
                                del recv_params
                                recv_params = request_handler_generator.throw(exc)
                            else:
                                del recv_params
                                recv_params = request_handler_generator.send(request)
                            finally:
                                request = None
                        except StopAsyncIteration:
                            break
                        except BaseException as exc:
                            # Remove asend()/athrow() frame
                            _utils.remove_traceback_frames_in_place(exc, 1)
                            raise
                finally:
                    request_handler_generator.close()

    return handler


def build_lowlevel_blocking_datagram_server_handler[*VarArgs, Request, Response, Address: Hashable](
    initializer: Callable[
        [_blocking_datagram_server.DatagramClientContext[Response, Address], *VarArgs],
        AbstractContextManager[BlockingDatagramClient[Response] | None],
    ],
    request_handler: BlockingDatagramRequestHandler[Request, Response],
    *args: *VarArgs,
) -> Callable[[_blocking_datagram_server.DatagramClientContext[Response, Address]], Generator[RecvParams | None, Request]]:
    """
    Creates a :term:`generator` function, usable by :meth:`.SelectorDatagramServer.serve`, from
    a :class:`.BlockingDatagramRequestHandler`.

    .. versionadded:: NEXT_VERSION

    Parameters:
        initializer: a callback returning a :term:`context manager` to create the final client interface and
                     set up the request handler generator.
                     The yielded value can be :data:`None` if the initializer failed silently.
        request_handler: the high-level interface which handles the incoming requests.

    Returns:
        a :term:`generator` function.
    """

    def handler(
        lowlevel_client: _blocking_datagram_server.DatagramClientContext[Response, Address], /
    ) -> Generator[RecvParams | None, Request]:
        with initializer(lowlevel_client, *args) as client:
            del lowlevel_client

            if client is None:
                # Initialization failed, but must not raise an exception.
                return

            request_handler_generator: Generator[RecvParams | None, Request] = request_handler.handle(client)
            try:
                yield from request_handler_generator
            except BaseException as exc:
                # Remove "yield from" frame
                _utils.remove_traceback_frames_in_place(exc, 1)
                raise

    return handler
