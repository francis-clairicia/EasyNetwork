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
"""Asynchronous Unix stream server implementation module.

.. versionadded:: 1.1
"""

from __future__ import annotations

__all__ = ["AsyncUnixStreamServer"]

import contextlib
import logging
import os
import pathlib
import weakref
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Generic, NoReturn, TypeVar, final

from .._typevars import _T_Request, _T_Response
from ..exceptions import ClientClosedError
from ..lowlevel import _unix_utils, _utils, constants
from ..lowlevel._final import runtime_final_class
from ..lowlevel.api_async.backend.abc import AsyncBackend, TaskGroup
from ..lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral
from ..lowlevel.api_async.servers import stream as _stream_server
from ..lowlevel.api_async.transports.abc import AsyncListener, AsyncStreamTransport
from ..lowlevel.api_async.transports.utils import aclose_forcefully
from ..lowlevel.socket import SocketProxy, UnixCredentials, UnixSocketAddress, UNIXSocketAttribute
from ..protocol import AnyStreamProtocolType
from . import _base
from .handlers import AsyncStreamClient, AsyncStreamRequestHandler, UNIXClientAttribute
from .misc import build_lowlevel_stream_server_handler


class AsyncUnixStreamServer(
    _base.BaseAsyncNetworkServerImpl[_stream_server.AsyncStreamServer[_T_Request, _T_Response], UnixSocketAddress],
    Generic[_T_Request, _T_Response],
):
    """
    An asynchronous Unix stream server.

    .. versionadded:: 1.1
    """

    __slots__ = (
        "__listener_factory",
        "__protocol",
        "__request_handler",
        "__max_recv_size",
        "__client_connection_log_level",
        "__unix_socket_to_delete",
    )

    def __init__(
        self,
        path: str | os.PathLike[str] | bytes | UnixSocketAddress,
        protocol: AnyStreamProtocolType[_T_Response, _T_Request],
        request_handler: AsyncStreamRequestHandler[_T_Request, _T_Response],
        backend: AsyncBackend | BuiltinAsyncBackendLiteral | None = None,
        *,
        backlog: int | None = None,
        mode: int | None = None,
        max_recv_size: int | None = None,
        log_client_connection: bool | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Parameters:
            path: Path of the socket.
            protocol: The :term:`protocol object` to use.
            request_handler: The request handler to use.
            backend: The :term:`asynchronous backend interface` to use.

        Keyword Arguments:
            backlog: is the maximum number of queued connections passed to :class:`~socket.socket.listen` (defaults to ``100``).
            mode: Permissions to set on the socket.
            max_recv_size: Read buffer size. If not given, a default reasonable value is used.
            log_client_connection: If :data:`True`, log clients connection/disconnection in :data:`logging.INFO` level.
                                   (This log will always be available in :data:`logging.DEBUG` level.)
            logger: If given, the logger instance to use.
        """
        super().__init__(
            backend=backend,
            servers_factory=_utils.weak_method_proxy(self.__activate_listeners),
            initialize_service=_utils.weak_method_proxy(self.__initialize_service),
            lowlevel_serve=_utils.weak_method_proxy(self.__lowlevel_serve),
            logger=logger or logging.getLogger(__name__),
        )

        from ..lowlevel._stream import _check_any_protocol

        path = _unix_utils.convert_unix_socket_address(path)

        _check_any_protocol(protocol)

        if not isinstance(request_handler, AsyncStreamRequestHandler):
            raise TypeError(f"Expected an AsyncStreamRequestHandler object, got {request_handler!r}")

        backend = self.backend()

        if backlog is None:
            backlog = 100

        if log_client_connection is None:
            log_client_connection = True

        if max_recv_size is None:
            max_recv_size = constants.DEFAULT_STREAM_BUFSIZE
        if not isinstance(max_recv_size, int) or max_recv_size <= 0:
            raise ValueError("'max_recv_size' must be a strictly positive integer")

        self.__listener_factory: Callable[[], Coroutine[Any, Any, AsyncListener[AsyncStreamTransport]]]
        self.__listener_factory = _utils.make_callback(
            backend.create_unix_stream_listener,
            path,
            backlog=backlog,
            mode=mode,
        )

        self.__protocol: AnyStreamProtocolType[_T_Response, _T_Request] = protocol
        self.__request_handler: AsyncStreamRequestHandler[_T_Request, _T_Response] = request_handler
        self.__max_recv_size: int = max_recv_size
        self.__client_connection_log_level: int
        if log_client_connection:
            self.__client_connection_log_level = logging.INFO
        else:
            self.__client_connection_log_level = logging.DEBUG
        self.__unix_socket_to_delete: dict[pathlib.Path, int] = {}

    async def server_close(self) -> None:
        unix_socket_to_delete = self.__unix_socket_to_delete
        self.__unix_socket_to_delete = {}
        try:
            await super().server_close()
        except self.backend().get_cancelled_exc_class():
            if unix_socket_to_delete:
                await self.backend().run_in_thread(self.__cleanup_unix_socket, unix_socket_to_delete, self.logger)
            raise
        else:
            if unix_socket_to_delete:
                await self.backend().run_in_thread(self.__cleanup_unix_socket, unix_socket_to_delete, self.logger)

    @staticmethod
    def __cleanup_unix_socket(unix_socket_to_delete: dict[pathlib.Path, int], logger: logging.Logger) -> None:
        while unix_socket_to_delete:
            path, prev_ino = unix_socket_to_delete.popitem()
            try:
                if os.stat(path).st_ino == prev_ino:
                    os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.error("Unable to clean up listening Unix socket %r: %s", os.fspath(path), exc)

    async def __activate_listeners(self) -> list[_stream_server.AsyncStreamServer[_T_Request, _T_Response]]:
        listener = await self.__listener_factory()

        local_name = UnixSocketAddress.from_raw(listener.extra(UNIXSocketAttribute.sockname))
        if (path := local_name.as_pathname()) is not None:
            self.__unix_socket_to_delete[path] = os.stat(path).st_ino

        server = _stream_server.AsyncStreamServer(
            listener,
            self.__protocol,
            max_recv_size=self.__max_recv_size,
        )
        return [server]

    async def __initialize_service(self, server_exit_stack: contextlib.AsyncExitStack) -> None:
        await self.__request_handler.service_init(
            await server_exit_stack.enter_async_context(contextlib.AsyncExitStack()),
            weakref.proxy(self),
        )

    async def __lowlevel_serve(
        self,
        server: _stream_server.AsyncStreamServer[_T_Request, _T_Response],
        task_group: TaskGroup,
    ) -> NoReturn:
        def disconnect_error_filter(exc: Exception) -> bool:  # pragma: no cover
            # Don't cover because theorically, socket.recv() should never get a BrokenPipeError.
            # It is a fallback for a very very edge case.
            return isinstance(exc, ConnectionError)

        handler = build_lowlevel_stream_server_handler(
            self.__client_initializer,
            self.__request_handler,
            logger=self.logger,
        )
        await server.serve(
            handler,
            task_group,
            disconnect_error_filter=disconnect_error_filter,
        )

    @contextlib.asynccontextmanager
    async def __client_initializer(
        self,
        lowlevel_client: _stream_server.ConnectedStreamClient[_T_Response],
    ) -> AsyncIterator[AsyncStreamClient[_T_Response] | None]:
        async with contextlib.AsyncExitStack() as client_exit_stack:
            client_exit_stack.enter_context(self._bind_server())

            client_address_raw = lowlevel_client.extra(UNIXSocketAttribute.peername, None)
            if client_address_raw is None:
                yield None
                return

            client = _ConnectedClientAPI(UnixSocketAddress.from_raw(client_address_raw), lowlevel_client)
            del lowlevel_client, client_address_raw

            client_exit_stack.enter_context(
                _base.ClientErrorHandler(
                    logger=self.logger,
                    client_address_cb=client.extra_attributes[UNIXClientAttribute.peer_name],
                    suppress_errors=ConnectionError,
                )
            )

            self.logger.log(
                self.__client_connection_log_level,
                "Accepted new connection (address = %s)",
                client.extra(UNIXClientAttribute.peer_name, UnixSocketAddress()),
            )
            client_exit_stack.callback(self.__log_client_disconnection, self.logger, self.__client_connection_log_level, client)
            client_exit_stack.push_async_callback(client._on_disconnect)

            try:
                yield client
            except BaseException as exc:
                _utils.remove_traceback_frames_in_place(exc, 1)
                raise

    @staticmethod
    def __log_client_disconnection(logger: logging.Logger, level: int, client: _ConnectedClientAPI[_T_Response]) -> None:
        logger.log(level, "%s disconnected", client.extra(UNIXClientAttribute.peer_name, UnixSocketAddress()))

    @_utils.inherit_doc(_base.BaseAsyncNetworkServerImpl)
    def get_addresses(self) -> Sequence[UnixSocketAddress]:
        return self._with_lowlevel_servers(
            lambda servers: tuple(
                UnixSocketAddress.from_raw(server.extra(UNIXSocketAttribute.sockname))
                for server in servers
                if not server.is_closing()
            )
        )

    def get_sockets(self) -> Sequence[SocketProxy]:
        """Gets the listeners sockets.

        Returns:
            a read-only sequence of :class:`.SocketProxy` objects.

            If the server is not running, an empty sequence is returned.
        """
        return self._with_lowlevel_servers(
            lambda servers: tuple(SocketProxy(server.extra(UNIXSocketAttribute.socket)) for server in servers)
        )


_T_Value = TypeVar("_T_Value")


@final
@runtime_final_class
class _ConnectedClientAPI(AsyncStreamClient[_T_Response]):
    __slots__ = (
        "__client",
        "__closing",
        "__send_lock",
        "__proxy",
        "__peer_name_cache",
        "__peer_creds_cache",
        "__extra_attributes_cache",
    )

    def __init__(
        self,
        initial_peer_name: UnixSocketAddress,
        client: _stream_server.ConnectedStreamClient[_T_Response],
    ) -> None:
        self.__client: _stream_server.ConnectedStreamClient[_T_Response] = client
        self.__closing: bool = False
        self.__send_lock = client.backend().create_fair_lock()
        self.__proxy: SocketProxy = SocketProxy(client.extra(UNIXSocketAttribute.socket))
        self.__peer_name_cache = initial_peer_name
        self.__peer_creds_cache = _unix_utils.UnixCredsContainer(self.__proxy)

        local_name = UnixSocketAddress.from_raw(client.extra(UNIXSocketAttribute.sockname, ""))

        self.__extra_attributes_cache: Mapping[Any, Callable[[], Any]] = MappingProxyType(
            {
                **client.extra_attributes,
                UNIXClientAttribute.socket: _utils.make_callback(self.__simple_attribute_return, self.__proxy),
                UNIXClientAttribute.local_name: _utils.make_callback(self.__simple_attribute_return, local_name),
                UNIXClientAttribute.peer_name: _utils.weak_method_proxy(self.__get_peer_name),
                UNIXClientAttribute.peer_credentials: _utils.weak_method_proxy(self.__get_peer_credentials),
            }
        )

    def __repr__(self) -> str:
        address = self.__get_peer_name()
        return f"<client with address {address} at {id(self):#x}>"

    def is_closing(self) -> bool:
        return self.__closing

    async def _on_disconnect(self) -> None:
        self.__closing = True
        async with self.__send_lock:  # If self.send_packet() took the lock, wait for it to finish
            pass

    async def aclose(self) -> None:
        async with contextlib.AsyncExitStack() as stack:
            try:
                await stack.enter_async_context(self.__send_lock)
            except self.backend().get_cancelled_exc_class():
                if not self.__closing:
                    self.__closing = True
                    await aclose_forcefully(self.__client)
                raise
            else:
                self.__closing = True
                await self.__client.aclose()

    async def send_packet(self, packet: _T_Response, /) -> None:
        async with self.__send_lock:
            if self.__closing:
                raise ClientClosedError("Closed client")
            await self.__client.send_packet(packet)

    def backend(self) -> AsyncBackend:
        return self.__client.backend()

    def __get_peer_name(self) -> UnixSocketAddress:
        if (peer_name := self.__peer_name_cache).is_unnamed():
            self.__peer_name_cache = peer_name = UnixSocketAddress.from_raw(self.__client.extra(UNIXSocketAttribute.peername))
        return peer_name

    def __get_peer_credentials(self) -> UnixCredentials:
        try:
            return self.__peer_creds_cache.get()
        except (OSError, NotImplementedError) as exc:
            from ..exceptions import TypedAttributeLookupError

            raise TypedAttributeLookupError("credentials not available") from exc

    @staticmethod
    def __simple_attribute_return(value: _T_Value) -> _T_Value:
        return value

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return self.__extra_attributes_cache
