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
"""Low-level asynchronous SSL transports module.

To use this module, the standard :mod:`ssl` module must be available.
"""

from __future__ import annotations

__all__ = ["AsyncTLSListener", "AsyncTLSStreamTransport"]

import contextlib
import dataclasses
import errno
import functools
import logging
import warnings
from collections import deque
from collections.abc import Callable, Coroutine, Iterable, Mapping
from typing import TYPE_CHECKING, Any, Final, NoReturn, Self, TypeVar, TypeVarTuple

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    _ssl_module = None
else:
    _ssl_module = _ssl
    del _ssl

from ....exceptions import UnsupportedOperation
from ... import _utils, constants, socket as socket_tools
from ..backend.abc import AsyncBackend, IEvent, ILock, TaskGroup
from .abc import AsyncListener, AsyncStreamReadTransport, AsyncStreamTransport
from .utils import aclose_forcefully

if TYPE_CHECKING:
    from ssl import MemoryBIO, SSLContext, SSLObject, SSLSession

    from _typeshed import WriteableBuffer

_T_PosArgs = TypeVarTuple("_T_PosArgs")
_T_Return = TypeVar("_T_Return")


@dataclasses.dataclass(repr=False, eq=False, slots=True, kw_only=True)
class AsyncTLSStreamTransport(AsyncStreamTransport):
    """
    SSL/TLS wrapper for a continuous stream transport.
    """

    _transport: AsyncStreamTransport
    _standard_compatible: bool
    _shutdown_timeout: float
    _ssl_object: SSLObject
    _read_bio: MemoryBIO
    _write_bio: MemoryBIO
    _data_deque: deque[memoryview] = dataclasses.field(init=False, default_factory=deque)
    __incoming_reader: _IncomingDataReader = dataclasses.field(init=False)
    __transport_send_lock: ILock = dataclasses.field(init=False)
    __transport_recv_lock: ILock = dataclasses.field(init=False)
    __closing: bool = dataclasses.field(init=False, default=False)
    __closed: IEvent = dataclasses.field(init=False)
    __tls_extra_atributes: Mapping[Any, Callable[[], Any]] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        backend = self._transport.backend()
        self.__incoming_reader = _IncomingDataReader(transport=self._transport)
        self.__transport_send_lock = backend.create_fair_lock()
        self.__transport_recv_lock = backend.create_fair_lock()
        self.__closed = backend.create_event()
        self.__tls_extra_atributes = socket_tools._get_tls_extra(self._ssl_object, self._standard_compatible)

    @classmethod
    async def wrap(
        cls,
        transport: AsyncStreamTransport,
        ssl_context: SSLContext,
        *,
        handshake_timeout: float | None = None,
        shutdown_timeout: float | None = None,
        server_side: bool | None = None,
        server_hostname: str | None = None,
        standard_compatible: bool = True,
        session: SSLSession | None = None,
    ) -> Self:
        """
        Parameters:
            transport: The transport to wrap.
            ssl_context: a :class:`ssl.SSLContext` object to use to create the transport.
            handshake_timeout: The time in seconds to wait for the TLS handshake to complete before aborting the connection.
                               ``60.0`` seconds if :data:`None` (default).
            shutdown_timeout: The time in seconds to wait for the SSL shutdown to complete before aborting the connection.
                              ``30.0`` seconds if :data:`None` (default).
            server_side: Indicates whether we are a client or a server for the handshake part. If it is set to :data:`None`,
                         it is deduced according to `server_hostname`.
            server_hostname: sets or overrides the hostname that the target server's certificate will be matched against.
                             If `server_side` is :data:`True`, you must pass a value for `server_hostname`.
            standard_compatible: If :data:`False`, skip the closing handshake when closing the connection,
                                 and don't raise an exception if the peer does the same.
            session: If an SSL session already exits, use it insead.
        """
        assert _ssl_module is not None, "stdlib ssl module not available"  # nosec assert_used

        if server_side is None:
            server_side = not server_hostname

        if handshake_timeout is None:
            handshake_timeout = constants.SSL_HANDSHAKE_TIMEOUT
        if shutdown_timeout is None:
            shutdown_timeout = constants.SSL_SHUTDOWN_TIMEOUT

        read_bio = _ssl_module.MemoryBIO()
        write_bio = _ssl_module.MemoryBIO()
        ssl_object = ssl_context.wrap_bio(
            read_bio,
            write_bio,
            server_side=server_side,
            server_hostname=server_hostname,
            session=session,
        )

        self = cls(
            _transport=transport,
            _standard_compatible=bool(standard_compatible),
            _shutdown_timeout=float(shutdown_timeout),
            _ssl_object=ssl_object,
            _read_bio=read_bio,
            _write_bio=write_bio,
        )

        try:
            with transport.backend().timeout(handshake_timeout):
                await self._retry_ssl_method(ssl_object.do_handshake)

            _ = ssl_object.getpeercert()
        except BaseException:
            self.__closing = True
            await aclose_forcefully(transport)
            raise
        return self

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            transport = self._transport
        except AttributeError:  # pragma: no cover
            # Technically possible but not with the common usage because dataclasses constructor does not raise.
            return
        if not transport.is_closing():
            msg = f"unclosed transport {self!r} pointing to {transport!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

    @_utils.inherit_doc(AsyncStreamTransport)
    def is_closing(self) -> bool:
        return self.__closing

    @_utils.inherit_doc(AsyncStreamTransport)
    async def aclose(self) -> None:
        assert _ssl_module is not None, "stdlib ssl module not available"  # nosec assert_used

        if self.__closing:
            await self.__closed.wait()
            return
        with contextlib.ExitStack() as stack:
            stack.callback(self.__closed.set)
            stack.callback(self.__incoming_reader.close)
            stack.callback(self._data_deque.clear)

            self.__closing = True
            if self._standard_compatible and not self._transport.is_closing():
                with self._transport.backend().move_on_after(self._shutdown_timeout) as shutdown_timeout_scope:
                    try:
                        try:
                            await self._retry_ssl_method(self._ssl_object.unwrap)
                        except OSError:
                            pass
                        self._read_bio.write_eof()
                        self._write_bio.write_eof()
                    except BaseException:
                        await aclose_forcefully(self._transport)
                        raise
                if shutdown_timeout_scope.cancelled_caught():
                    return

            await self._transport.aclose()

    @_utils.inherit_doc(AsyncStreamTransport)
    def backend(self) -> AsyncBackend:
        return self._transport.backend()

    @_utils.inherit_doc(AsyncStreamTransport)
    async def recv(self, bufsize: int) -> bytes:
        assert _ssl_module is not None, "stdlib ssl module not available"  # nosec assert_used
        try:
            return await self._retry_ssl_method(self._ssl_object.read, bufsize)
        except _ssl_module.SSLZeroReturnError:
            return b""
        except _ssl_module.SSLError as exc:
            if _utils.is_ssl_eof_error(exc):
                if not self._standard_compatible:
                    return b""
            raise

    @_utils.inherit_doc(AsyncStreamTransport)
    async def recv_into(self, buffer: WriteableBuffer) -> int:
        assert _ssl_module is not None, "stdlib ssl module not available"  # nosec assert_used
        nbytes = memoryview(buffer).nbytes or 1024
        try:
            return await self._retry_ssl_method(self._ssl_object.read, nbytes, buffer)  # type: ignore[arg-type]
        except _ssl_module.SSLZeroReturnError:
            return 0
        except _ssl_module.SSLError as exc:
            if _utils.is_ssl_eof_error(exc):
                if not self._standard_compatible:
                    return 0
            raise

    @_utils.inherit_doc(AsyncStreamTransport)
    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        if self.__closing:
            raise _utils.error_from_errno(errno.ECONNABORTED)
        self._data_deque.append(memoryview(data))
        del data
        return await self.__flush_data_to_send()

    @_utils.inherit_doc(AsyncStreamTransport)
    async def send_all_from_iterable(self, iterable_of_data: Iterable[bytes | bytearray | memoryview]) -> None:
        if self.__closing:
            raise _utils.error_from_errno(errno.ECONNABORTED)
        self._data_deque.extend(map(memoryview, iterable_of_data))
        del iterable_of_data
        return await self.__flush_data_to_send()

    async def __flush_data_to_send(self) -> None:
        assert _ssl_module is not None, "stdlib ssl module not available"  # nosec assert_used
        try:
            await self._retry_ssl_method(self.__write_all_to_ssl_object, self._ssl_object, self._data_deque)
        except _ssl_module.SSLZeroReturnError as exc:
            raise _utils.error_from_errno(errno.ECONNRESET) from exc

    @staticmethod
    def __write_all_to_ssl_object(ssl_object: SSLObject, write_backlog: deque[memoryview]) -> None:
        while write_backlog:
            data = write_backlog[0]
            if data.itemsize != 1:
                write_backlog[0] = data = data.cast("B")
            sent = ssl_object.write(data)
            if sent < len(data):
                write_backlog[0] = data[sent:]
            else:
                del write_backlog[0]

    async def send_eof(self) -> None:
        """
        Closes the write end of the stream after the buffered write data is flushed.

        Raises:
            UnsupportedOperation: SSL/TLS API does not support sending EOF (for now).
        """
        raise UnsupportedOperation("SSL/TLS API does not support sending EOF.")

    async def _retry_ssl_method(
        self,
        ssl_object_method: Callable[[*_T_PosArgs], _T_Return],
        *args: *_T_PosArgs,
    ) -> _T_Return:
        assert _ssl_module is not None, "stdlib ssl module not available"  # nosec assert_used
        while True:
            try:
                result = ssl_object_method(*args)
            except _ssl_module.SSLWantReadError:
                try:
                    # Flush any pending writes first
                    async with self.__transport_send_lock:
                        if self._write_bio.pending:
                            await self._transport.send_all(self._write_bio.read())

                    async with self.__transport_recv_lock:
                        await self.__incoming_reader.readinto(self._read_bio)
                except OSError:
                    self._read_bio.write_eof()
                    self._write_bio.write_eof()
                    raise
            except _ssl_module.SSLWantWriteError:
                async with self.__transport_send_lock:
                    await self._transport.send_all(self._write_bio.read())
            except _ssl_module.SSLError:
                self._read_bio.write_eof()
                self._write_bio.write_eof()
                raise
            else:
                # Flush any pending writes first
                async with self.__transport_send_lock:
                    if self._write_bio.pending:
                        await self._transport.send_all(self._write_bio.read())

                return result

    @property
    @_utils.inherit_doc(AsyncStreamTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {
            **self._transport.extra_attributes,
            **self.__tls_extra_atributes,
        }


class AsyncTLSListener(AsyncListener[AsyncTLSStreamTransport]):
    """
    Listener with SSL/TLS wrapper for a continuous stream transport.
    """

    __slots__ = (
        "__listener",
        "__ssl_context",
        "__standard_compatible",
        "__handshake_timeout",
        "__shutdown_timeout",
        "__handshake_error_handler",
        "__tls_extra_attributes",
    )

    def __init__(
        self,
        listener: AsyncListener[AsyncStreamTransport],
        ssl_context: SSLContext,
        *,
        handshake_timeout: float | None = None,
        shutdown_timeout: float | None = None,
        standard_compatible: bool = True,
        handshake_error_handler: Callable[[Exception], None] | None = None,
    ) -> None:
        """
        .. versionchanged:: 1.1
            Added `handshake_error_handler` parameter.

        Parameters:
            listener: The listener to wrap.
            ssl_context: a :class:`ssl.SSLContext` object to use to create the client transport.
            handshake_timeout: The time in seconds to wait for the TLS handshake to complete before aborting the connection.
                               ``60.0`` seconds if :data:`None` (default).
            shutdown_timeout: The time in seconds to wait for the SSL shutdown to complete before aborting the connection.
                              ``30.0`` seconds if :data:`None` (default).
            standard_compatible: If :data:`False`, skip the closing handshake when closing the connection,
                                 and don't raise an exception if the peer does the same.
            handshake_error_handler: a callback to be used on handshake failure. By default, emits a warning log.
        """
        super().__init__()

        self.__listener: AsyncListener[AsyncStreamTransport] = listener
        self.__ssl_context: SSLContext = ssl_context
        self.__handshake_timeout: float | None = handshake_timeout
        self.__shutdown_timeout: float | None = shutdown_timeout
        self.__standard_compatible: bool = standard_compatible
        self.__handshake_error_handler: Callable[[Exception], None] | None = handshake_error_handler
        self.__tls_extra_attributes = self.__make_tls_extra_attributes(self.__ssl_context, self.__standard_compatible)

    def __del__(self, *, _warn: _utils.WarnCallback = warnings.warn) -> None:
        try:
            listener = self.__listener
        except AttributeError:  # pragma: no cover
            # Technically possible but not with the common usage because this constructor does not raise.
            return
        if not listener.is_closing():
            msg = f"unclosed listener {self!r} pointing to {listener!r} (and cannot be closed synchronously)"
            _warn(msg, ResourceWarning, source=self)

    @_utils.inherit_doc(AsyncListener)
    def is_closing(self) -> bool:
        return self.__listener.is_closing()

    @_utils.inherit_doc(AsyncListener)
    async def aclose(self) -> None:
        return await self.__listener.aclose()

    @_utils.inherit_doc(AsyncListener)
    async def serve(
        self,
        handler: Callable[[AsyncTLSStreamTransport], Coroutine[Any, Any, None]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        listener = self.__listener

        @functools.wraps(handler, assigned=[])
        async def tls_handler_wrapper(stream: AsyncStreamTransport, /) -> None:
            try:
                stream = await AsyncTLSStreamTransport.wrap(
                    stream,
                    self.__ssl_context,
                    server_side=True,
                    handshake_timeout=self.__handshake_timeout,
                    shutdown_timeout=self.__shutdown_timeout,
                    standard_compatible=self.__standard_compatible,
                )
            except stream.backend().get_cancelled_exc_class():
                await aclose_forcefully(stream)
                raise
            except Exception as exc:
                await aclose_forcefully(stream)
                handshake_error_handler = self.__handshake_error_handler
                if handshake_error_handler is None:
                    self.__default_handshake_error_handler(exc)
                else:
                    try:
                        handshake_error_handler(exc)
                    except Exception as error_handler_exc:
                        self.__default_handshake_error_handler(error_handler_exc)
            else:
                await handler(stream)

        await listener.serve(tls_handler_wrapper, task_group)

    @staticmethod
    def __default_handshake_error_handler(exc: Exception) -> None:
        logger = logging.getLogger(__name__)
        logger.warning("Error in client task (during TLS handshake)", exc_info=exc)

    @_utils.inherit_doc(AsyncListener)
    def backend(self) -> AsyncBackend:
        return self.__listener.backend()

    @staticmethod
    def __make_tls_extra_attributes(ssl_context: SSLContext, standard_compatible: bool) -> dict[Any, Callable[[], Any]]:
        return {
            socket_tools.TLSAttribute.sslcontext: lambda: ssl_context,
            socket_tools.TLSAttribute.standard_compatible: lambda: standard_compatible,
        }

    @property
    @_utils.inherit_doc(AsyncListener)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {
            **self.__listener.extra_attributes,
            **self.__tls_extra_attributes,
        }


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _IncomingDataReader:
    transport: AsyncStreamReadTransport
    max_size: Final[int] = 256 * 1024  # 256KiB

    buffer: bytearray | None = dataclasses.field(init=False)
    buffer_view: memoryview = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self.buffer = bytearray(self.max_size)
        self.buffer_view = memoryview(self.buffer)

    async def readinto(self, read_bio: MemoryBIO) -> int:
        if (nbytes := await self.transport.recv_into(buffer := self.buffer_view)) > 0:
            return read_bio.write(buffer[:nbytes])
        read_bio.write_eof()
        return 0

    def close(self) -> None:
        self.buffer_view.release()
        self.buffer = None
