# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import asyncio.trsock
import contextlib
import logging
import os
import ssl
from collections.abc import Callable
from errno import errorcode as errno_errorcode
from socket import SHUT_RDWR, SHUT_WR
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.constants import ACCEPT_CAPACITY_ERRNOS, NOT_CONNECTED_SOCKET_ERRNOS
from easynetwork.lowlevel.socket import SocketAttribute, TLSAttribute
from easynetwork.lowlevel.std_asyncio.stream.listener import (
    AbstractAcceptedSocketFactory,
    AcceptedSocketFactory,
    AcceptedSSLSocketFactory,
    ListenerSocketAdapter,
)
from easynetwork.lowlevel.std_asyncio.stream.socket import AsyncioTransportStreamSocketAdapter, RawStreamSocketAdapter
from easynetwork.lowlevel.std_asyncio.tasks import CancelScope, TaskGroup as AsyncIOTaskGroup

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

from ....tools import PlatformMarkers
from ...base import BaseTestSocket


class BaseTestTransportStreamSocket:
    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader(mock_asyncio_stream_reader_factory: Callable[[], MagicMock]) -> MagicMock:
        return mock_asyncio_stream_reader_factory()

    @pytest.fixture
    @staticmethod
    def mock_tcp_socket(mock_tcp_socket: MagicMock) -> MagicMock:
        mock_tcp_socket.getsockname.return_value = ("127.0.0.1", 11111)
        mock_tcp_socket.getpeername.return_value = ("127.0.0.1", 12345)
        return mock_tcp_socket

    @pytest.fixture
    @staticmethod
    def asyncio_writer_extra_info(mock_tcp_socket: MagicMock) -> dict[str, Any]:
        return {
            "socket": mock_tcp_socket,
            "sockname": mock_tcp_socket.getsockname.return_value,
            "peername": mock_tcp_socket.getpeername.return_value,
        }

    @pytest.fixture
    @staticmethod
    def mock_asyncio_writer(
        asyncio_writer_extra_info: dict[str, Any],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock = mock_asyncio_stream_writer_factory()
        mock.get_extra_info.side_effect = asyncio_writer_extra_info.get
        return mock


@pytest.mark.asyncio
class TestAsyncioTransportStreamSocketAdapter(BaseTestTransportStreamSocket):
    @pytest.fixture
    @staticmethod
    def mock_ssl_object(mock_ssl_context: MagicMock, mocker: MockerFixture) -> MagicMock:
        mock_ssl_object = mocker.NonCallableMagicMock(spec=ssl.SSLObject)
        mock_ssl_object.context = mock_ssl_context
        mock_ssl_object.getpeercert.return_value = mocker.sentinel.peercert
        mock_ssl_object.cipher.return_value = mocker.sentinel.cipher
        mock_ssl_object.compression.return_value = mocker.sentinel.compression
        mock_ssl_object.version.return_value = mocker.sentinel.tls_version
        return mock_ssl_object

    @pytest.fixture
    @staticmethod
    def add_ssl_extra_to_transport(
        asyncio_writer_extra_info: dict[str, Any],
        mock_ssl_context: MagicMock,
        mock_ssl_object: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        asyncio_writer_extra_info.update(
            {
                "sslcontext": mock_ssl_context,
                "ssl_object": mock_ssl_object,
                "peercert": mocker.sentinel.peercert,
                "cipher": mocker.sentinel.cipher,
                "compression": mocker.sentinel.compression,
            }
        )

    @pytest.fixture
    @staticmethod
    def socket(mock_asyncio_reader: MagicMock, mock_asyncio_writer: MagicMock) -> AsyncioTransportStreamSocketAdapter:
        mock_asyncio_writer.can_write_eof.return_value = True
        return AsyncioTransportStreamSocketAdapter(mock_asyncio_reader, mock_asyncio_writer)

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    @pytest.mark.parametrize("can_write_eof", [False, True], ids=lambda p: f"can_write_eof=={p}")
    @pytest.mark.parametrize("wait_close_raise_error", [False, True], ids=lambda p: f"wait_close_raise_error=={p}")
    @pytest.mark.parametrize("write_eof_raise_error", [False, True], ids=lambda p: f"write_eof_raise_error=={p}")
    async def test____aclose____close_transport_and_wait(
        self,
        transport_is_closing: bool,
        can_write_eof: bool,
        wait_close_raise_error: bool,
        write_eof_raise_error: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_writer.is_closing.return_value = transport_is_closing
        mock_asyncio_writer.can_write_eof.return_value = can_write_eof
        if wait_close_raise_error:
            mock_asyncio_writer.wait_closed.side_effect = OSError
        if write_eof_raise_error:
            mock_asyncio_writer.write_eof.side_effect = OSError

        # Act
        await socket.aclose()

        # Assert
        if transport_is_closing:
            mock_asyncio_writer.close.assert_not_called()
            mock_asyncio_writer.wait_closed.assert_awaited_once_with()
            mock_asyncio_writer.transport.abort.assert_not_called()
        else:
            if can_write_eof:
                mock_asyncio_writer.write_eof.assert_called_once_with()
            else:
                mock_asyncio_writer.write_eof.assert_not_called()
            mock_asyncio_writer.close.assert_called_once_with()
            mock_asyncio_writer.wait_closed.assert_awaited_once_with()
            mock_asyncio_writer.transport.abort.assert_not_called()

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____aclose____abort_transport_if_cancelled(
        self,
        transport_is_closing: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_writer.is_closing.return_value = transport_is_closing
        mock_asyncio_writer.wait_closed.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            await socket.aclose()

        # Assert
        if transport_is_closing:
            mock_asyncio_writer.close.assert_not_called()
            mock_asyncio_writer.wait_closed.assert_awaited_once_with()
        else:
            mock_asyncio_writer.close.assert_called_once_with()
            mock_asyncio_writer.wait_closed.assert_awaited_once_with()
        mock_asyncio_writer.transport.abort.assert_not_called()

    @pytest.mark.usefixtures("add_ssl_extra_to_transport")
    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____aclose____abort_transport_if_cancelled____ssl(
        self,
        transport_is_closing: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_writer.is_closing.return_value = transport_is_closing
        mock_asyncio_writer.wait_closed.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            await socket.aclose()

        # Assert
        if transport_is_closing:
            mock_asyncio_writer.close.assert_not_called()
            mock_asyncio_writer.wait_closed.assert_awaited_once_with()
            mock_asyncio_writer.transport.abort.assert_not_called()
        else:
            mock_asyncio_writer.close.assert_called_once_with()
            mock_asyncio_writer.wait_closed.assert_awaited_once_with()
            mock_asyncio_writer.transport.abort.assert_called_once_with()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    async def test____is_closing____return_internal_flag(
        self,
        transport_closed: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        if transport_closed:
            await socket.aclose()
            mock_asyncio_writer.reset_mock()
        mock_asyncio_writer.is_closing.side_effect = AssertionError

        # Act
        state = socket.is_closing()

        # Assert
        mock_asyncio_writer.is_closing.assert_not_called()
        assert state is transport_closed

    async def test____recv____read_from_reader(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_reader: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_reader.read.return_value = b"data"

        # Act
        data: bytes = await socket.recv(1024)

        # Assert
        mock_asyncio_reader.read.assert_awaited_once_with(1024)
        assert data == b"data"

    async def test____recv____null_bufsize(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_reader: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_reader.read.return_value = b""

        # Act
        data: bytes = await socket.recv(0)

        # Assert
        mock_asyncio_reader.read.assert_awaited_once_with(0)
        assert data == b""

    async def test____recv____negative_bufsize_error(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_reader: MagicMock,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(ValueError):
            await socket.recv(-1)

        # Assert
        mock_asyncio_reader.read.assert_not_awaited()

    async def test____send_all____write_and_drain(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.send_all(b"data to send")

        # Assert
        mock_asyncio_writer.write.assert_called_once_with(b"data to send")
        mock_asyncio_writer.writelines.assert_not_called()
        mock_asyncio_writer.drain.assert_awaited_once_with()

    async def test____send_all_from_iterable____writelines_and_drain(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        written_chunks: list[bytes] = []

        mock_asyncio_writer.writelines.side_effect = written_chunks.extend

        # Act
        await socket.send_all_from_iterable([b"data", b"to", b"send"])

        # Assert
        mock_asyncio_writer.write.assert_not_called()
        mock_asyncio_writer.writelines.assert_called_once()
        mock_asyncio_writer.drain.assert_awaited_once_with()
        assert written_chunks == [b"data", b"to", b"send"]

    @pytest.mark.parametrize("can_write_eof", [False, True], ids=lambda p: f"can_write_eof=={p}")
    async def test____send_eof____write_eof(
        self,
        can_write_eof: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_writer.can_write_eof.return_value = can_write_eof
        mock_asyncio_writer.write_eof.return_value = None

        # Act & Assert
        if can_write_eof:
            await socket.send_eof()
            mock_asyncio_writer.write_eof.assert_called_once_with()
        else:
            with pytest.raises(UnsupportedOperation):
                await socket.send_eof()
            mock_asyncio_writer.write_eof.assert_not_called()

    async def test____get_extra_info____returns_socket_info(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert socket.extra(SocketAttribute.socket) is mock_tcp_socket
        assert socket.extra(SocketAttribute.family) == mock_tcp_socket.family
        assert socket.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert socket.extra(SocketAttribute.peername) == ("127.0.0.1", 12345)

    @pytest.mark.usefixtures("add_ssl_extra_to_transport")
    async def test____get_extra_info____returns_ssl_info(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        assert socket.extra(TLSAttribute.sslcontext) is mock_ssl_context
        assert socket.extra(TLSAttribute.peercert) is mocker.sentinel.peercert
        assert socket.extra(TLSAttribute.cipher) is mocker.sentinel.cipher
        assert socket.extra(TLSAttribute.compression) is mocker.sentinel.compression
        assert socket.extra(TLSAttribute.tls_version) is mocker.sentinel.tls_version
        assert socket.extra(TLSAttribute.standard_compatible) is True


@pytest.mark.asyncio
class TestListenerSocketAdapter(BaseTestTransportStreamSocket, BaseTestSocket):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_async_socket_cls(mock_async_socket: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(f"{ListenerSocketAdapter.__module__}.AsyncSocket", return_value=mock_async_socket)

    @pytest.fixture
    @classmethod
    def mock_tcp_listener_socket(
        cls,
        mock_tcp_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_socket = mock_tcp_socket_factory()
        cls.set_local_address_to_socket_mock(mock_socket, mock_socket.family, ("127.0.0.1", 11111))
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_socket)
        return mock_socket

    @pytest.fixture
    @staticmethod
    def mock_async_socket(
        mock_async_socket: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_tcp_listener_socket: MagicMock,
    ) -> MagicMock:
        mock_async_socket.socket = mock_tcp_listener_socket
        mock_async_socket.accept.return_value = (mock_tcp_socket, ("127.0.0.1", 12345))
        return mock_async_socket

    @pytest.fixture
    @staticmethod
    def accepted_socket_factory(mocker: MockerFixture) -> MagicMock:
        return mocker.MagicMock(spec=AbstractAcceptedSocketFactory)

    @pytest.fixture
    @staticmethod
    def handler(mocker: MockerFixture) -> AsyncMock:
        handler = mocker.async_stub("handler")
        handler.return_value = None
        return handler

    @pytest.fixture
    @staticmethod
    def listener(
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_listener_socket: MagicMock,
        accepted_socket_factory: MagicMock,
    ) -> ListenerSocketAdapter[Any]:
        return ListenerSocketAdapter(mock_tcp_listener_socket, event_loop, accepted_socket_factory)

    async def test____dunder_init____invalid_socket_type(
        self,
        event_loop: asyncio.AbstractEventLoop,
        mock_udp_socket: MagicMock,
        accepted_socket_factory: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_STREAM' socket is expected$"):
            _ = ListenerSocketAdapter(mock_udp_socket, event_loop, accepted_socket_factory)

    async def test____is_closing____default(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_async_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_async_socket.is_closing.return_value = mocker.sentinel.is_closing

        # Act
        state = listener.is_closing()

        # Assert
        assert state is mocker.sentinel.is_closing
        mock_async_socket.is_closing.assert_called_once_with()

    async def test____aclose____close_socket(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await listener.aclose()

        # Assert
        mock_async_socket.aclose.assert_awaited_once_with()

    async def test____serve____default(
        self,
        event_loop: asyncio.AbstractEventLoop,
        listener: ListenerSocketAdapter[Any],
        mock_async_socket: MagicMock,
        accepted_socket_factory: MagicMock,
        handler: AsyncMock,
        mock_tcp_socket_factory: Callable[[], MagicMock],
        mock_stream_socket_adapter_factory: Callable[[], MagicMock],
        fake_cancellation_cls: type[BaseException],
    ) -> None:
        # Arrange
        stream = mock_stream_socket_adapter_factory()
        client_socket = mock_tcp_socket_factory()
        accepted_socket_factory.connect.return_value = stream
        mock_async_socket.accept.side_effect = [client_socket, fake_cancellation_cls]

        # Act
        async with AsyncIOTaskGroup() as task_group:
            with pytest.raises(fake_cancellation_cls):
                await listener.serve(handler, task_group)

        # Assert
        accepted_socket_factory.connect.assert_awaited_once_with(client_socket, event_loop)
        handler.assert_awaited_once_with(stream)

    @pytest.mark.parametrize(
        "exc",
        [
            *(OSError(errno, os.strerror(errno)) for errno in sorted(NOT_CONNECTED_SOCKET_ERRNOS)),
            Exception(),
            asyncio.CancelledError(),
            BaseException(),
        ],
        ids=repr,
    )
    async def test____serve____connect____error_raised(
        self,
        exc: BaseException,
        event_loop: asyncio.AbstractEventLoop,
        listener: ListenerSocketAdapter[Any],
        mock_async_socket: MagicMock,
        accepted_socket_factory: MagicMock,
        handler: AsyncMock,
        mock_tcp_socket_factory: Callable[[], MagicMock],
        fake_cancellation_cls: type[BaseException],
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.DEBUG)
        client_socket = mock_tcp_socket_factory()
        accepted_socket_factory.connect.side_effect = exc
        mock_async_socket.accept.side_effect = [client_socket, fake_cancellation_cls]

        # Act
        with pytest.raises(BaseExceptionGroup) if type(exc) is BaseException else contextlib.nullcontext():
            async with AsyncIOTaskGroup() as task_group:
                with pytest.raises(fake_cancellation_cls):
                    await listener.serve(handler, task_group)

        # Assert
        accepted_socket_factory.connect.assert_awaited_once_with(client_socket, event_loop)
        handler.assert_not_awaited()
        client_socket.close.assert_called_once_with()

        match exc:
            case asyncio.CancelledError():
                assert len(caplog.records) == 0
                accepted_socket_factory.log_connection_error.assert_not_called()
            case OSError():
                # ENOTCONN error should not create a big Traceback error but only a warning (at least)
                assert len(caplog.records) == 1
                assert caplog.records[0].levelno == logging.WARNING
                assert caplog.records[0].message == "A client connection was interrupted just after listener.accept()"
            case _:
                assert len(caplog.records) == 0
                accepted_socket_factory.log_connection_error.assert_called_once_with(
                    mocker.ANY,  # logger
                    exc,
                )

    @PlatformMarkers.skipif_platform_win32
    @pytest.mark.parametrize("errno_value", sorted(ACCEPT_CAPACITY_ERRNOS), ids=errno_errorcode.__getitem__)
    async def test____serve____accept_capacity_error(
        self,
        errno_value: int,
        listener: ListenerSocketAdapter[Any],
        mock_async_socket: MagicMock,
        accepted_socket_factory: MagicMock,
        handler: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)
        accepted_socket_factory.connect.side_effect = AssertionError
        mock_async_socket.accept.side_effect = OSError(errno_value, os.strerror(errno_value))

        # Act
        async with AsyncIOTaskGroup() as task_group:
            # It retries every 100 ms, so in 975 ms it will retry at 0, 100, ..., 900
            # = 10 times total
            with CancelScope(deadline=asyncio.get_running_loop().time() + 0.975):
                await listener.serve(handler, task_group)

        # Assert
        accepted_socket_factory.connect.assert_not_awaited()
        handler.assert_not_awaited()
        assert len(caplog.records) == 10
        for record in caplog.records:
            assert "retrying" in record.message
            assert (
                record.exc_info is not None
                and isinstance(record.exc_info[1], OSError)
                and record.exc_info[1].errno == errno_value
            )

    async def test____serve____reraise_other_OSErrors(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_async_socket: MagicMock,
        accepted_socket_factory: MagicMock,
        handler: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)
        accepted_socket_factory.connect.side_effect = AssertionError
        exc = OSError()
        mock_async_socket.accept.side_effect = exc

        # Act
        async with AsyncIOTaskGroup() as task_group:
            with pytest.raises(OSError) as exc_info:
                await listener.serve(handler, task_group)

        # Assert
        accepted_socket_factory.connect.assert_not_awaited()
        handler.assert_not_awaited()
        assert len(caplog.records) == 0
        assert exc_info.value is exc

    async def test____get_extra_info____returns_socket_info(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        assert listener.extra(SocketAttribute.socket) is mock_tcp_listener_socket
        assert listener.extra(SocketAttribute.family) == mock_tcp_listener_socket.family
        assert listener.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert listener.extra(SocketAttribute.peername, mocker.sentinel.no_value) is mocker.sentinel.no_value


@pytest.mark.asyncio
class TestAcceptedSocketFactory(BaseTestTransportStreamSocket, BaseTestSocket):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_async_socket_cls(mock_async_socket: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(f"{ListenerSocketAdapter.__module__}.AsyncSocket", return_value=mock_async_socket)

    @pytest.fixture(params=[False, True], ids=lambda boolean: f"use_asyncio_transport=={boolean}")
    @staticmethod
    def use_asyncio_transport(request: Any) -> bool:
        return request.param

    @pytest.fixture
    @staticmethod
    def mock_transport_stream_socket_adapter_cls(mock_stream_socket_adapter: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            f"{ListenerSocketAdapter.__module__}.AsyncioTransportStreamSocketAdapter",
            return_value=mock_stream_socket_adapter,
        )

    @pytest.fixture
    @staticmethod
    def mock_raw_stream_socket_adapter_cls(mock_stream_socket_adapter: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            f"{ListenerSocketAdapter.__module__}.RawStreamSocketAdapter",
            return_value=mock_stream_socket_adapter,
        )

    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader_cls(mock_asyncio_reader: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("asyncio.streams.StreamReader", return_value=mock_asyncio_reader)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_writer_cls(mock_asyncio_writer: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("asyncio.streams.StreamWriter", return_value=mock_asyncio_writer)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader_protocol(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=asyncio.streams.StreamReaderProtocol)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_transport(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=asyncio.Transport)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader_protocol_cls(mock_asyncio_reader_protocol: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("asyncio.streams.StreamReaderProtocol", return_value=mock_asyncio_reader_protocol)

    @pytest.fixture
    @staticmethod
    def mock_event_loop_connect_accepted_socket(
        event_loop: asyncio.AbstractEventLoop,
        mocker: MockerFixture,
        mock_asyncio_transport: MagicMock,
    ) -> AsyncMock:
        return mocker.patch.object(
            event_loop,
            "connect_accepted_socket",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_transport, mocker.sentinel.final_protocol),
        )

    @pytest.fixture
    @staticmethod
    def accepted_socket(
        use_asyncio_transport: bool,
    ) -> AcceptedSocketFactory:
        return AcceptedSocketFactory(use_asyncio_transport=use_asyncio_transport)

    async def test____log_connection_error____error_log(
        self,
        caplog: pytest.LogCaptureFixture,
        accepted_socket: AcceptedSocketFactory,
    ) -> None:
        # Arrange
        logger = logging.getLogger(__name__)
        caplog.set_level(logging.ERROR, logger.name)
        exc = BaseException()

        # Act
        accepted_socket.log_connection_error(logger, exc)

        # Assert
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].message == "Error in client task"
        assert caplog.records[0].exc_info is not None and caplog.records[0].exc_info[1] is exc

    async def test____connect____creates_new_stream_socket(
        self,
        accepted_socket: AcceptedSocketFactory,
        use_asyncio_transport: bool,
        event_loop: asyncio.AbstractEventLoop,
        mock_event_loop_connect_accepted_socket: AsyncMock,
        mock_transport_stream_socket_adapter_cls: MagicMock,
        mock_raw_stream_socket_adapter_cls: MagicMock,
        mock_asyncio_reader_protocol: MagicMock,
        mock_asyncio_reader_protocol_cls: MagicMock,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_reader_cls: MagicMock,
        mock_asyncio_reader: MagicMock,
        mock_asyncio_writer_cls: MagicMock,
        mock_asyncio_writer: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        socket = await accepted_socket.connect(mock_tcp_socket, event_loop)

        # Assert
        assert socket is mock_stream_socket_adapter
        if use_asyncio_transport:
            mock_raw_stream_socket_adapter_cls.assert_not_called()
            mock_asyncio_reader_cls.assert_called_once_with(limit=mocker.ANY, loop=event_loop)
            mock_asyncio_reader_protocol_cls.assert_called_once_with(mock_asyncio_reader, loop=event_loop)
            mock_event_loop_connect_accepted_socket.assert_awaited_once_with(
                mocker.ANY,  # protocol_factory
                mock_tcp_socket,
                ssl=None,
                ssl_handshake_timeout=None,
                ssl_shutdown_timeout=None,
            )
            mock_asyncio_writer_cls.assert_called_once_with(
                mock_asyncio_transport,
                mock_asyncio_reader_protocol,
                mock_asyncio_reader,
                event_loop,
            )
            mock_transport_stream_socket_adapter_cls.assert_called_once_with(
                mock_asyncio_reader,
                mock_asyncio_writer,
            )
        else:
            mock_raw_stream_socket_adapter_cls.assert_called_once_with(
                mock_tcp_socket,
                event_loop,
            )
            mock_asyncio_reader_cls.assert_not_called()
            mock_asyncio_reader_protocol_cls.assert_not_called()
            mock_asyncio_writer_cls.assert_not_called()
            mock_event_loop_connect_accepted_socket.assert_not_called()
            mock_transport_stream_socket_adapter_cls.assert_not_called()


@pytest.mark.asyncio
class TestAcceptedSSLSocketFactory(BaseTestTransportStreamSocket):
    @pytest.fixture(scope="class")
    @staticmethod
    def ssl_handshake_timeout() -> float:
        return 123456.789

    @pytest.fixture(scope="class")
    @staticmethod
    def ssl_shutdown_timeout() -> float:
        return 9876543.21

    @pytest.fixture
    @staticmethod
    def mock_transport_stream_socket_adapter_cls(mock_stream_socket_adapter: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            f"{ListenerSocketAdapter.__module__}.AsyncioTransportStreamSocketAdapter",
            return_value=mock_stream_socket_adapter,
        )

    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader_cls(mock_asyncio_reader: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("asyncio.streams.StreamReader", return_value=mock_asyncio_reader)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_writer_cls(mock_asyncio_writer: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("asyncio.streams.StreamWriter", return_value=mock_asyncio_writer)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader_protocol(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=asyncio.streams.StreamReaderProtocol)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_transport(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=asyncio.Transport)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader_protocol_cls(mock_asyncio_reader_protocol: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("asyncio.streams.StreamReaderProtocol", return_value=mock_asyncio_reader_protocol)

    @pytest.fixture
    @staticmethod
    def mock_event_loop_connect_accepted_socket(
        event_loop: asyncio.AbstractEventLoop,
        mocker: MockerFixture,
        mock_asyncio_transport: MagicMock,
    ) -> AsyncMock:
        return mocker.patch.object(
            event_loop,
            "connect_accepted_socket",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_transport, mocker.sentinel.final_protocol),
        )

    @pytest.fixture
    @staticmethod
    def accepted_socket(
        mock_ssl_context: MagicMock,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
    ) -> AcceptedSSLSocketFactory:
        return AcceptedSSLSocketFactory(
            ssl_context=mock_ssl_context,
            ssl_handshake_timeout=ssl_handshake_timeout,
            ssl_shutdown_timeout=ssl_shutdown_timeout,
        )

    async def test____log_connection_error____error_log(
        self,
        caplog: pytest.LogCaptureFixture,
        accepted_socket: AcceptedSocketFactory,
    ) -> None:
        # Arrange
        logger = logging.getLogger(__name__)
        caplog.set_level(logging.ERROR, logger.name)
        exc = BaseException()

        # Act
        accepted_socket.log_connection_error(logger, exc)

        # Assert
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].message == "Error in client task (during TLS handshake)"
        assert caplog.records[0].exc_info is not None and caplog.records[0].exc_info[1] is exc

    async def test____connect____creates_new_stream_socket(
        self,
        accepted_socket: AcceptedSSLSocketFactory,
        mock_ssl_context: MagicMock,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
        event_loop: asyncio.AbstractEventLoop,
        mock_event_loop_connect_accepted_socket: AsyncMock,
        mock_transport_stream_socket_adapter_cls: MagicMock,
        mock_asyncio_reader_protocol: MagicMock,
        mock_asyncio_reader_protocol_cls: MagicMock,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_reader_cls: MagicMock,
        mock_asyncio_reader: MagicMock,
        mock_asyncio_writer_cls: MagicMock,
        mock_asyncio_writer: MagicMock,
        mock_tcp_socket: MagicMock,
        mock_stream_socket_adapter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        socket = await accepted_socket.connect(mock_tcp_socket, event_loop)

        # Assert
        assert socket is mock_stream_socket_adapter

        mock_asyncio_reader_cls.assert_called_once_with(limit=mocker.ANY, loop=event_loop)
        mock_asyncio_reader_protocol_cls.assert_called_once_with(mock_asyncio_reader, loop=event_loop)
        mock_event_loop_connect_accepted_socket.assert_awaited_once_with(
            mocker.ANY,  # protocol_factory
            mock_tcp_socket,
            ssl=mock_ssl_context,
            ssl_handshake_timeout=ssl_handshake_timeout,
            ssl_shutdown_timeout=ssl_shutdown_timeout,
        )
        mock_asyncio_writer_cls.assert_called_once_with(
            mock_asyncio_transport,
            mock_asyncio_reader_protocol,
            mock_asyncio_reader,
            event_loop,
        )
        mock_transport_stream_socket_adapter_cls.assert_called_once_with(
            mock_asyncio_reader,
            mock_asyncio_writer,
        )


@pytest.mark.asyncio
class TestRawStreamSocketAdapter(BaseTestSocket):
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_async_socket_cls(mock_async_socket: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(f"{RawStreamSocketAdapter.__module__}.AsyncSocket", return_value=mock_async_socket)

    @pytest.fixture
    @classmethod
    def mock_tcp_socket(cls, mock_tcp_socket: MagicMock) -> MagicMock:
        cls.set_local_address_to_socket_mock(mock_tcp_socket, mock_tcp_socket.family, ("127.0.0.1", 11111))
        cls.set_remote_address_to_socket_mock(mock_tcp_socket, mock_tcp_socket.family, ("127.0.0.1", 12345))
        return mock_tcp_socket

    @pytest.fixture
    @staticmethod
    def mock_async_socket(
        mock_async_socket: MagicMock,
        mock_tcp_socket: MagicMock,
    ) -> MagicMock:
        mock_async_socket.socket = mock_tcp_socket
        return mock_async_socket

    @pytest.fixture
    @staticmethod
    def socket(event_loop: asyncio.AbstractEventLoop, mock_tcp_socket: MagicMock) -> RawStreamSocketAdapter:
        return RawStreamSocketAdapter(mock_tcp_socket, event_loop)

    async def test____dunder_init____invalid_socket_type(
        self,
        event_loop: asyncio.AbstractEventLoop,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_STREAM' socket is expected$"):
            _ = RawStreamSocketAdapter(mock_udp_socket, event_loop)

    async def test____is_closing____default(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_async_socket.is_closing.return_value = mocker.sentinel.is_closing

        # Act
        state = socket.is_closing()

        # Assert
        assert state is mocker.sentinel.is_closing
        mock_async_socket.is_closing.assert_called_once_with()

    @pytest.mark.parametrize("shutdown_raise_error", [OSError, None])
    async def test____aclose____close_socket(
        self,
        shutdown_raise_error: type[BaseException] | None,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        if shutdown_raise_error is not None:
            mock_async_socket.shutdown.side_effect = shutdown_raise_error

        # Act
        await socket.aclose()

        # Assert
        mock_async_socket.shutdown.assert_awaited_once_with(SHUT_RDWR)
        mock_async_socket.aclose.assert_awaited_once_with()

    async def test____recv____returns_data_from_async_socket(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_async_socket.recv.return_value = b"data"

        # Act
        data: bytes = await socket.recv(123456789)

        # Assert
        assert data == b"data"
        mock_async_socket.recv.assert_awaited_once_with(123456789)

    async def test____recv_into____returns_data_from_async_socket(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        def recv_into_side_effect(buf: bytearray | memoryview) -> int:
            with memoryview(buf) as buf:
                buf[:4] = b"data"
                return 4

        mock_async_socket.recv_into.side_effect = recv_into_side_effect
        buffer = bytearray(1024)

        # Act
        nbytes = await socket.recv_into(buffer)

        # Assert
        assert nbytes == 4
        assert buffer[:nbytes] == b"data"
        mock_async_socket.recv_into.assert_awaited_once_with(buffer)

    async def test____send_all____sends_data_to_async_socket(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_async_socket.sendall.return_value = None

        # Act
        await socket.send_all(b"data")

        # Assert
        mock_async_socket.sendall.assert_awaited_once_with(b"data")

    async def test____send_all_from_iterable____use_async_socket_sendmsg(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_async_socket.sendmsg.return_value = None

        # Act
        await socket.send_all_from_iterable([b"data", b"to", b"send"])

        # Assert
        mock_async_socket.sendmsg.assert_awaited_once_with([b"data", b"to", b"send"])
        mock_async_socket.sendall.assert_not_called()

    async def test____send_all_from_iterable____fallback_to_sendall(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_async_socket.sendmsg.side_effect = UnsupportedOperation

        # Act
        await socket.send_all_from_iterable([b"data", b"to", b"send"])

        # Assert
        mock_async_socket.sendmsg.assert_awaited_once()
        assert mock_async_socket.sendall.await_args_list == list(map(mocker.call, [b"data", b"to", b"send"]))

    async def test____send_eof____shutdown_socket(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_async_socket.shutdown.return_value = None
        mock_async_socket.did_shutdown_SHUT_WR = False

        # Act
        await socket.send_eof()

        # Assert
        mock_async_socket.shutdown.assert_awaited_once_with(SHUT_WR)

    async def test____get_extra_info____returns_socket_info(
        self,
        socket: RawStreamSocketAdapter,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert socket.extra(SocketAttribute.socket) is mock_tcp_socket
        assert socket.extra(SocketAttribute.family) == mock_tcp_socket.family
        assert socket.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert socket.extra(SocketAttribute.peername) == ("127.0.0.1", 12345)
