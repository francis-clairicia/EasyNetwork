# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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
"""Low-level asynchronous transports module"""

from __future__ import annotations

__all__ = ["AsyncTLSListener", "AsyncTLSStreamTransport"]

import contextlib
import dataclasses
import errno
import functools
import logging
from collections.abc import Callable, Coroutine, Mapping
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
from ..backend.abc import TaskGroup
from ..backend.factory import current_async_backend
from . import abc as transports
from .utils import aclose_forcefully

if TYPE_CHECKING:
    import ssl as _typing_ssl

    from _typeshed import WriteableBuffer

_T_PosArgs = TypeVarTuple("_T_PosArgs")
_T_Return = TypeVar("_T_Return")


@dataclasses.dataclass(repr=False, eq=False, slots=True, kw_only=True)
class AsyncTLSStreamTransport(transports.AsyncStreamTransport, transports.AsyncBufferedStreamReadTransport):
    _transport: transports.AsyncStreamTransport
    _standard_compatible: bool
    _shutdown_timeout: float
    _ssl_object: _typing_ssl.SSLObject
    _read_bio: _typing_ssl.MemoryBIO
    _write_bio: _typing_ssl.MemoryBIO
    __incoming_reader: _IncomingDataReader = dataclasses.field(init=False)
    __closing: bool = dataclasses.field(init=False, default=False)

    def __post_init__(self) -> None:
        if isinstance(self._transport, transports.AsyncBufferedStreamReadTransport):
            self.__incoming_reader = _BufferedIncomingDataReader(transport=self._transport)
        else:
            self.__incoming_reader = _IncomingDataReader(transport=self._transport)

    @classmethod
    async def wrap(
        cls,
        transport: transports.AsyncStreamTransport,
        ssl_context: _typing_ssl.SSLContext,
        *,
        handshake_timeout: float | None = None,
        shutdown_timeout: float | None = None,
        server_side: bool | None = None,
        server_hostname: str | None = None,
        standard_compatible: bool = True,
        session: _typing_ssl.SSLSession | None = None,
    ) -> Self:
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
            with current_async_backend().timeout(handshake_timeout):
                await self._retry_ssl_method(ssl_object.do_handshake)

            _ = ssl_object.getpeercert()
        except BaseException:
            await aclose_forcefully(transport)
            raise
        return self

    @_utils.inherit_doc(transports.AsyncStreamTransport)
    def is_closing(self) -> bool:
        return self.__closing

    @_utils.inherit_doc(transports.AsyncStreamTransport)
    async def aclose(self) -> None:
        with contextlib.ExitStack() as stack:
            stack.callback(self.__incoming_reader.close)

            self.__closing = True
            if self._standard_compatible:
                with current_async_backend().move_on_after(self._shutdown_timeout) as shutdown_timeout_scope:
                    try:
                        await self._retry_ssl_method(self._ssl_object.unwrap)
                        self._read_bio.write_eof()
                        self._write_bio.write_eof()
                    except BaseException:
                        await aclose_forcefully(self._transport)
                        raise
                if shutdown_timeout_scope.cancelled_caught():
                    return

            await self._transport.aclose()

    @_utils.inherit_doc(transports.AsyncStreamTransport)
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

    @_utils.inherit_doc(transports.AsyncBufferedStreamReadTransport)
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

    @_utils.inherit_doc(transports.AsyncStreamTransport)
    async def send_all(self, data: bytes | bytearray | memoryview) -> None:
        assert _ssl_module is not None, "stdlib ssl module not available"  # nosec assert_used
        try:
            await self._retry_ssl_method(self._ssl_object.write, data)
        except _ssl_module.SSLZeroReturnError as exc:
            raise _utils.error_from_errno(errno.ECONNRESET) from exc

    @_utils.inherit_doc(transports.AsyncStreamTransport)
    async def send_eof(self) -> None:
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
                    if self._write_bio.pending:
                        await self._transport.send_all(self._write_bio.read())

                    await self.__incoming_reader.readinto(self._read_bio)
                except OSError:
                    self._read_bio.write_eof()
                    self._write_bio.write_eof()
                    raise
            except _ssl_module.SSLWantWriteError:
                await self._transport.send_all(self._write_bio.read())
            except _ssl_module.SSLError:
                self._read_bio.write_eof()
                self._write_bio.write_eof()
                raise
            else:
                # Flush any pending writes first
                if self._write_bio.pending:
                    await self._transport.send_all(self._write_bio.read())

                return result

    @property
    @_utils.inherit_doc(transports.AsyncStreamTransport)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {
            **self._transport.extra_attributes,
            **socket_tools._get_tls_extra(self._ssl_object),
            socket_tools.TLSAttribute.standard_compatible: lambda: self._standard_compatible,
        }


class AsyncTLSListener(transports.AsyncListener[AsyncTLSStreamTransport]):
    __slots__ = (
        "__listener",
        "__ssl_context",
        "__standard_compatible",
        "__handshake_timeout",
        "__shutdown_timeout",
    )

    def __init__(
        self,
        listener: transports.AsyncListener[transports.AsyncStreamTransport],
        ssl_context: _typing_ssl.SSLContext,
        *,
        handshake_timeout: float | None = None,
        shutdown_timeout: float | None = None,
        standard_compatible: bool = True,
    ) -> None:
        super().__init__()
        self.__listener: transports.AsyncListener[transports.AsyncStreamTransport] = listener
        self.__ssl_context: _typing_ssl.SSLContext = ssl_context
        self.__handshake_timeout: float | None = handshake_timeout
        self.__shutdown_timeout: float | None = shutdown_timeout
        self.__standard_compatible: bool = standard_compatible

    @_utils.inherit_doc(transports.AsyncListener)
    def is_closing(self) -> bool:
        return self.__listener.is_closing()

    @_utils.inherit_doc(transports.AsyncListener)
    async def aclose(self) -> None:
        return await self.__listener.aclose()

    @_utils.inherit_doc(transports.AsyncListener)
    async def serve(
        self,
        handler: Callable[[AsyncTLSStreamTransport], Coroutine[Any, Any, None]],
        task_group: TaskGroup | None = None,
    ) -> NoReturn:
        listener = self.__listener
        logger = logging.getLogger(__name__)

        @functools.wraps(handler)
        async def tls_handler_wrapper(stream: transports.AsyncStreamTransport, /) -> None:
            try:
                stream = await AsyncTLSStreamTransport.wrap(
                    stream,
                    self.__ssl_context,
                    server_side=True,
                    handshake_timeout=self.__handshake_timeout,
                    shutdown_timeout=self.__shutdown_timeout,
                    standard_compatible=self.__standard_compatible,
                )
            except current_async_backend().get_cancelled_exc_class():
                await aclose_forcefully(stream)
                raise
            except BaseException as exc:
                await aclose_forcefully(stream)

                logger.error("Error in client task (during TLS handshake)", exc_info=exc)

                # Only reraise base exceptions
                if not isinstance(exc, Exception):
                    raise
            else:
                await handler(stream)

        await listener.serve(tls_handler_wrapper, task_group)

    @property
    @_utils.inherit_doc(transports.AsyncListener)
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {
            **self.__listener.extra_attributes,
            socket_tools.TLSAttribute.sslcontext: lambda: self.__ssl_context,
            socket_tools.TLSAttribute.standard_compatible: lambda: self.__standard_compatible,
        }


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _IncomingDataReader:
    transport: transports.AsyncStreamReadTransport
    max_size: Final[int] = 256 * 1024  # 256KiB

    async def readinto(self, read_bio: _typing_ssl.MemoryBIO) -> int:
        data = await self.transport.recv(self.max_size)
        if data:
            return read_bio.write(data)
        read_bio.write_eof()
        return 0

    def close(self) -> None:
        pass


@dataclasses.dataclass(kw_only=True, eq=False, slots=True)
class _BufferedIncomingDataReader(_IncomingDataReader):
    transport: transports.AsyncBufferedStreamReadTransport
    buffer: bytearray | None = dataclasses.field(init=False)
    buffer_view: memoryview = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self.buffer = bytearray(self.max_size)
        self.buffer_view = memoryview(self.buffer)

    async def readinto(self, read_bio: _typing_ssl.MemoryBIO) -> int:
        buffer = self.buffer_view
        nbytes = await self.transport.recv_into(buffer)
        if nbytes:
            return read_bio.write(buffer[:nbytes])
        read_bio.write_eof()
        return 0

    def close(self) -> None:
        self.buffer_view.release()
        self.buffer = None
