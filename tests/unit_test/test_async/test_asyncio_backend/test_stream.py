# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import asyncio.trsock
import ssl
from collections.abc import Callable
from socket import SHUT_RDWR, SHUT_WR
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.socket import SocketAttribute, TLSAttribute
from easynetwork_asyncio.stream.listener import (
    AbstractAcceptedSocketFactory,
    AcceptedSocketFactory,
    AcceptedSSLSocketFactory,
    ListenerSocketAdapter,
)
from easynetwork_asyncio.stream.socket import AsyncioTransportStreamSocketAdapter, RawStreamSocketAdapter

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

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
    def socket(mock_asyncio_reader: MagicMock, mock_asyncio_writer: MagicMock) -> AsyncioTransportStreamSocketAdapter:
        mock_asyncio_writer.can_write_eof.return_value = True
        return AsyncioTransportStreamSocketAdapter(mock_asyncio_reader, mock_asyncio_writer)

    @pytest.mark.parametrize("can_write_eof", [False, True], ids=lambda p: f"can_write_eof=={p}")
    @pytest.mark.parametrize("wait_close_raise_error", [False, True], ids=lambda p: f"wait_close_raise_error=={p}")
    @pytest.mark.parametrize("write_eof_rais_error", [False, True], ids=lambda p: f"write_eof_rais_error=={p}")
    async def test____aclose____close_transport_and_wait(
        self,
        can_write_eof: bool,
        wait_close_raise_error: bool,
        write_eof_rais_error: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_writer.can_write_eof.return_value = can_write_eof
        if wait_close_raise_error:
            mock_asyncio_writer.wait_closed.side_effect = OSError
        if write_eof_rais_error:
            mock_asyncio_writer.write_eof.side_effect = OSError

        # Act
        await socket.aclose()

        # Assert
        if can_write_eof:
            mock_asyncio_writer.write_eof.assert_called_once_with()
        else:
            mock_asyncio_writer.write_eof.assert_not_called()
        mock_asyncio_writer.close.assert_called_once_with()
        mock_asyncio_writer.wait_closed.assert_awaited_once_with()
        mock_asyncio_writer.transport.abort.assert_not_called()

    async def test____aclose____wait_only_if_already_closing(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_writer.is_closing.return_value = True

        # Act
        await socket.aclose()

        # Assert
        mock_asyncio_writer.close.assert_not_called()
        mock_asyncio_writer.wait_closed.assert_awaited_once_with()
        mock_asyncio_writer.transport.abort.assert_not_called()

    async def test____aclose____abort_transport_if_cancelled(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_writer.wait_closed.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            await socket.aclose()

        # Assert
        mock_asyncio_writer.close.assert_called_once_with()
        mock_asyncio_writer.wait_closed.assert_awaited_once_with()
        mock_asyncio_writer.transport.abort.assert_called_once_with()

    async def test____is_closing____return_writer_state(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_asyncio_writer.is_closing.return_value = mocker.sentinel.is_closing

        # Act
        state = socket.is_closing()

        # Assert
        mock_asyncio_writer.is_closing.assert_called_once_with()
        assert state is mocker.sentinel.is_closing

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

    async def test____send_all_from_iterable____single_yield_calls_write_instead(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.send_all_from_iterable(iter([b"data"]))

        # Assert
        mock_asyncio_writer.write.assert_called_once_with(b"data")
        mock_asyncio_writer.writelines.assert_not_called()
        mock_asyncio_writer.drain.assert_awaited_once_with()

    async def test____send_eof____write_eof(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_writer.write_eof.return_value = None

        # Act
        await socket.send_eof()

        # Assert
        mock_asyncio_writer.write_eof.assert_called_once_with()

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

    async def test____get_extra_info____returns_ssl_info(
        self,
        asyncio_writer_extra_info: dict[str, Any],
        socket: AsyncioTransportStreamSocketAdapter,
        mock_ssl_object: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        asyncio_writer_extra_info.update({"ssl_object": mock_ssl_object})

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

    async def test____send_all_from_iterable____sends_concatenated_data_to_async_socket(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_async_socket.sendall.return_value = None

        # Act
        await socket.send_all_from_iterable([b"data", b"to", b"send"])

        # Assert
        mock_async_socket.sendall.assert_awaited_once_with(b"datatosend")

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
