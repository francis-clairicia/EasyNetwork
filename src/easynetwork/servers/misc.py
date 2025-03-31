# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
    "build_lowlevel_datagram_server_handler",
    "build_lowlevel_stream_server_handler",
]

import inspect
import logging
from collections.abc import AsyncGenerator, Callable, Hashable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import TypeVar, TypeVarTuple

from .._typevars import _T_Request, _T_Response
from ..lowlevel import _utils
from ..lowlevel.api_async.servers import datagram as _lowlevel_datagram_server, stream as _lowlevel_stream_server
from .handlers import AsyncDatagramClient, AsyncDatagramRequestHandler, AsyncStreamClient, AsyncStreamRequestHandler

_T_Address = TypeVar("_T_Address", bound=Hashable)

_T_VarArgs = TypeVarTuple("_T_VarArgs")


def build_lowlevel_stream_server_handler(
    initializer: Callable[
        [_lowlevel_stream_server.ConnectedStreamClient[_T_Response], *_T_VarArgs],
        AbstractAsyncContextManager[AsyncStreamClient[_T_Response] | None],
    ],
    request_handler: AsyncStreamRequestHandler[_T_Request, _T_Response],
    *args: *_T_VarArgs,
    logger: logging.Logger | None = None,
) -> Callable[[_lowlevel_stream_server.ConnectedStreamClient[_T_Response]], AsyncGenerator[float | None, _T_Request]]:
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
        lowlevel_client: _lowlevel_stream_server.ConnectedStreamClient[_T_Response], /
    ) -> AsyncGenerator[float | None, _T_Request]:
        async with initializer(lowlevel_client, *args) as client, AsyncExitStack() as request_handler_exit_stack:
            del lowlevel_client

            if client is None:
                # Initialization failed, but must not raise an exception.
                return

            request_handler_generator: AsyncGenerator[float | None, _T_Request]
            request: _T_Request | None
            timeout: float | None

            _on_connection_hook = request_handler.on_connection(client)
            if isinstance(_on_connection_hook, AsyncGenerator):
                try:
                    timeout = await anext(_on_connection_hook)
                except StopAsyncIteration:
                    pass
                else:
                    while True:
                        try:
                            try:
                                request = yield timeout
                            except GeneratorExit:  # pragma: no cover
                                raise
                            except BaseException as exc:
                                timeout = await _on_connection_hook.athrow(exc)
                            else:
                                timeout = await _on_connection_hook.asend(request)
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
                    timeout = await anext(request_handler_generator)
                except StopAsyncIteration:
                    await _transports_utils.aclose_forcefully(client)
                    return
                else:
                    while True:
                        try:
                            try:
                                request = yield timeout
                            except GeneratorExit:  # pragma: no cover
                                raise
                            except BaseException as exc:
                                timeout = await request_handler_generator.athrow(exc)
                            else:
                                timeout = await request_handler_generator.asend(request)
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


def build_lowlevel_datagram_server_handler(
    initializer: Callable[
        [_lowlevel_datagram_server.DatagramClientContext[_T_Response, _T_Address], *_T_VarArgs],
        AbstractAsyncContextManager[AsyncDatagramClient[_T_Response] | None],
    ],
    request_handler: AsyncDatagramRequestHandler[_T_Request, _T_Response],
    *args: *_T_VarArgs,
) -> Callable[
    [_lowlevel_datagram_server.DatagramClientContext[_T_Response, _T_Address]],
    AsyncGenerator[float | None, _T_Request],
]:
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
        lowlevel_client: _lowlevel_datagram_server.DatagramClientContext[_T_Response, _T_Address], /
    ) -> AsyncGenerator[float | None, _T_Request]:
        async with initializer(lowlevel_client, *args) as client:
            del lowlevel_client

            if client is None:
                # Initialization failed, but must not raise an exception.
                return

            request_handler_generator = request_handler.handle(client)
            request: _T_Request | None
            timeout: float | None
            try:
                timeout = await anext(request_handler_generator)
            except StopAsyncIteration:
                return
            else:
                while True:
                    try:
                        try:
                            request = yield timeout
                        except GeneratorExit:  # pragma: no cover
                            raise
                        except BaseException as exc:
                            timeout = await request_handler_generator.athrow(exc)
                        else:
                            timeout = await request_handler_generator.asend(request)
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
