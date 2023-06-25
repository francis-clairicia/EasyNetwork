# -*- coding: utf-8 -*-
# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import asyncio.trsock
from typing import TYPE_CHECKING, Any, Callable

from easynetwork.api_async.backend.abc import AbstractAcceptedSocket
from easynetwork_asyncio.stream.listener import AcceptedSocket, AcceptedSSLSocket, ListenerSocketAdapter
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
    def asyncio_writer_extra_info() -> dict[str, Any]:
        return {}

    @pytest.fixture
    @staticmethod
    def mock_asyncio_writer(
        asyncio_writer_extra_info: dict[str, Any],
        mock_tcp_socket: MagicMock,
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        asyncio_writer_extra_info.update(
            {
                "socket": mock_tcp_socket,
                "sockname": mock_tcp_socket.getsockname.return_value,
                "peername": mock_tcp_socket.getpeername.return_value,
            }
        )
        mock = mock_asyncio_stream_writer_factory()
        mock.get_extra_info.side_effect = asyncio_writer_extra_info.get
        return mock


@pytest.mark.asyncio
class TestTransportBasedStreamSocket(BaseTestTransportStreamSocket):
    @pytest.fixture
    @staticmethod
    def socket(mock_asyncio_reader: MagicMock, mock_asyncio_writer: MagicMock) -> AsyncioTransportStreamSocketAdapter:
        return AsyncioTransportStreamSocketAdapter(mock_asyncio_reader, mock_asyncio_writer)

    async def test____dunder_init____transport_not_connected(
        self,
        asyncio_writer_extra_info: dict[str, Any],
        mock_asyncio_reader: MagicMock,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        from errno import ENOTCONN

        ### asyncio.Transport implementations explicitly set peername to None if the socket is not connected
        asyncio_writer_extra_info["peername"] = None

        # Act & Assert
        with pytest.raises(OSError) as exc_info:
            AsyncioTransportStreamSocketAdapter(mock_asyncio_reader, mock_asyncio_writer)

        assert exc_info.value.errno == ENOTCONN
        mock_asyncio_writer.get_extra_info.assert_called_with("peername")

    async def test____aclose____close_transport_and_wait(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.aclose()

        # Assert
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

    @pytest.mark.parametrize("exception_cls", [*ConnectionError.__subclasses__(), TimeoutError])
    async def test____aclose____ignore_socket_error(
        self,
        exception_cls: type[ConnectionError],
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_writer.wait_closed.side_effect = exception_cls

        # Act
        await socket.aclose()

        # Assert
        mock_asyncio_writer.close.assert_called_once_with()
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

    async def test____context____close_transport_and_wait_at_end(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange

        # Act
        async with socket:
            mock_asyncio_writer.close.assert_not_called()

        # Assert
        mock_asyncio_writer.close.assert_called_once_with()
        mock_asyncio_writer.wait_closed.assert_awaited_once_with()

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

    async def test____recv____null_bufsize_directly_return(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_reader: MagicMock,
    ) -> None:
        # Arrange

        # Act
        data: bytes = await socket.recv(0)

        # Assert
        mock_asyncio_reader.read.assert_not_awaited()
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

    async def test____sendall____write_and_drain(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.sendall(b"data to send")

        # Assert
        mock_asyncio_writer.write.assert_called_once_with(b"data to send")
        mock_asyncio_writer.drain.assert_awaited_once_with()

    async def test____getsockname____return_sockname_extra_info(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        asyncio_writer_extra_info: dict[str, Any],
    ) -> None:
        # Arrange

        # Act
        laddr = socket.get_local_address()

        # Assert
        assert laddr == asyncio_writer_extra_info["sockname"]

    async def test____getpeername____return_peername_extra_info(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        asyncio_writer_extra_info: dict[str, Any],
    ) -> None:
        # Arrange

        # Act
        raddr = socket.get_remote_address()

        # Assert
        assert raddr == asyncio_writer_extra_info["peername"]

    async def test____socket____returns_transport_socket(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        transport_socket = socket.socket()

        # Assert
        assert transport_socket is mock_tcp_socket


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
        return mocker.MagicMock(spec=lambda socket, loop: None)

    @pytest.fixture
    @staticmethod
    def listener(
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_listener_socket: MagicMock,
        accepted_socket_factory: Callable[..., Any],
    ) -> ListenerSocketAdapter:
        return ListenerSocketAdapter(mock_tcp_listener_socket, event_loop, accepted_socket_factory)

    async def test____dunder_init____default(
        self,
        listener: ListenerSocketAdapter,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act

        # Assert
        assert listener.socket() is mock_tcp_listener_socket

    async def test____get_local_address____returns_socket_address(
        self,
        listener: ListenerSocketAdapter,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        local_address = listener.get_local_address()

        # Assert
        mock_tcp_listener_socket.getsockname.assert_called_once_with()
        assert local_address == ("127.0.0.1", 11111)

    async def test____is_closing____default(
        self,
        listener: ListenerSocketAdapter,
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
        listener: ListenerSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await listener.aclose()

        # Assert
        mock_async_socket.aclose.assert_awaited_once_with()

    async def test____accept____create_accepted_socket(
        self,
        event_loop: asyncio.AbstractEventLoop,
        listener: ListenerSocketAdapter,
        accepted_socket_factory: MagicMock,
        mock_async_socket: MagicMock,
        mock_socket_factory: Callable[[], MagicMock],
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_accepted_socket = mock_socket_factory()
        mock_accepted_socket = mocker.NonCallableMagicMock(spec=AbstractAcceptedSocket)
        accepted_socket_factory.return_value = mock_accepted_socket

        # Act
        accepted_socket = await listener.accept()

        # Assert
        mock_async_socket.accept.assert_awaited_once_with()
        accepted_socket_factory.assert_called_once_with(mock_tcp_socket, event_loop)
        assert accepted_socket is mock_accepted_socket


@pytest.mark.asyncio
class TestAcceptedSocket(BaseTestTransportStreamSocket, BaseTestSocket):
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
    def mock_stream_socket_adapter(mock_stream_socket_adapter: MagicMock) -> MagicMock:
        mock_stream_socket_adapter.get_remote_address.return_value = ("127.0.0.1", 12345)
        return mock_stream_socket_adapter

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
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_socket: MagicMock,
        use_asyncio_transport: bool,
    ) -> AcceptedSocket:
        return AcceptedSocket(mock_tcp_socket, event_loop, use_asyncio_transport=use_asyncio_transport)

    async def test____connect____creates_new_stream_socket(
        self,
        accepted_socket: AcceptedSocket,
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
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        # Act
        socket = await accepted_socket.connect()

        # Assert
        assert socket is mock_stream_socket_adapter
        if use_asyncio_transport:
            mock_raw_stream_socket_adapter_cls.assert_not_called()
            mock_asyncio_reader_cls.assert_called_once_with(MAX_STREAM_BUFSIZE, event_loop)
            mock_asyncio_reader_protocol_cls.assert_called_once_with(mock_asyncio_reader, loop=event_loop)
            mock_event_loop_connect_accepted_socket.assert_awaited_once_with(
                mocker.ANY,  # protocol_factory
                mock_tcp_socket,
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
class TestAcceptedSSLSocket(BaseTestTransportStreamSocket):
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
    def mock_stream_socket_adapter(mock_stream_socket_adapter: MagicMock) -> MagicMock:
        mock_stream_socket_adapter.get_remote_address.return_value = ("127.0.0.1", 12345)
        return mock_stream_socket_adapter

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
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_socket: MagicMock,
        mock_ssl_context: MagicMock,
        ssl_handshake_timeout: float,
        ssl_shutdown_timeout: float,
    ) -> AcceptedSSLSocket:
        return AcceptedSSLSocket(
            mock_tcp_socket,
            event_loop,
            mock_ssl_context,
            ssl_handshake_timeout=ssl_handshake_timeout,
            ssl_shutdown_timeout=ssl_shutdown_timeout,
        )

    async def test____connect____creates_new_stream_socket(
        self,
        accepted_socket: AcceptedSSLSocket,
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
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        # Act
        socket = await accepted_socket.connect()

        # Assert
        assert socket is mock_stream_socket_adapter

        mock_asyncio_reader_cls.assert_called_once_with(MAX_STREAM_BUFSIZE, event_loop)
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

    async def test____dunder_init____default(
        self,
        socket: RawStreamSocketAdapter,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act

        # Assert
        assert socket.socket() is mock_tcp_socket

    async def test____get_local_address____returns_socket_address(
        self,
        socket: RawStreamSocketAdapter,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        local_address = socket.get_local_address()

        # Assert
        mock_tcp_socket.getsockname.assert_called_once_with()
        assert local_address == ("127.0.0.1", 11111)

    async def test____get_remote_address____returns_peer_address(
        self,
        socket: RawStreamSocketAdapter,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_tcp_socket.getpeername.assert_called_once_with()

        # Act
        remote_address = socket.get_remote_address()

        # Assert
        mock_tcp_socket.getpeername.assert_called_once_with()
        assert remote_address == ("127.0.0.1", 12345)

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

    async def test____aclose____close_socket(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.aclose()

        # Assert
        mock_async_socket.aclose.assert_awaited_once_with()

    async def test____context____close_socket(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        async with socket:
            mock_async_socket.aclose.assert_not_awaited()

        # Assert
        mock_async_socket.aclose.assert_awaited_once_with()

    async def test_____recv____returns_data_from_async_socket(
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

    async def test_____sendall____sends_data_to_async_socket(
        self,
        socket: RawStreamSocketAdapter,
        mock_async_socket: MagicMock,
    ) -> None:
        # Arrange
        mock_async_socket.sendall.return_value = None

        # Act
        await socket.sendall(b"data")

        # Assert
        mock_async_socket.sendall.assert_awaited_once_with(b"data")
