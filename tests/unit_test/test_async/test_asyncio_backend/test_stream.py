# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
import asyncio.trsock
import socket
from typing import TYPE_CHECKING, Any, Callable

from easynetwork_asyncio.stream.listener import ListenerSocketAdapter
from easynetwork_asyncio.stream.socket import StreamSocketAdapter

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


class BaseTestStreamSocket:
    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader(mocker: MockerFixture) -> MagicMock:
        return mocker.MagicMock(spec=asyncio.StreamReader)

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
        mocker: MockerFixture,
    ) -> MagicMock:
        asyncio_writer_extra_info.update(
            {
                "socket": mock_tcp_socket,
                "sockname": mock_tcp_socket.getsockname.return_value,
                "peername": mock_tcp_socket.getpeername.return_value,
            }
        )
        mock = mocker.MagicMock(spec=asyncio.StreamWriter)
        mock.get_extra_info.side_effect = asyncio_writer_extra_info.get
        return mock


@pytest.mark.asyncio
class TestStreamSocket(BaseTestStreamSocket):
    @pytest.fixture
    @staticmethod
    def socket(mock_asyncio_reader: MagicMock, mock_asyncio_writer: MagicMock) -> StreamSocketAdapter:
        return StreamSocketAdapter(mock_asyncio_reader, mock_asyncio_writer)

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
            StreamSocketAdapter(mock_asyncio_reader, mock_asyncio_writer)

        assert exc_info.value.errno == ENOTCONN
        mock_asyncio_writer.get_extra_info.assert_called_with("peername")

    async def test____dunder_init____explicit_remote_address(
        self,
        mock_asyncio_reader: MagicMock,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange
        remote_address = ("explicit_address", 4444)

        # Act
        socket = StreamSocketAdapter(mock_asyncio_reader, mock_asyncio_writer, remote_address=remote_address)

        # Assert
        assert socket.get_remote_address() == remote_address

    async def test____aclose____close_transport_and_wait(
        self,
        socket: StreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.aclose()

        # Assert
        mock_asyncio_writer.close.assert_called_once_with()
        mock_asyncio_writer.wait_closed.assert_awaited_once_with()
        mock_asyncio_writer.transport.abort.assert_not_called()

    @pytest.mark.parametrize("exception_cls", ConnectionError.__subclasses__())
    async def test____aclose____ignore_connection_error(
        self,
        exception_cls: type[ConnectionError],
        socket: StreamSocketAdapter,
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

    async def test____abort____abort_transport_and_exit(
        self,
        socket: StreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.abort()

        # Assert
        mock_asyncio_writer.transport.abort.assert_called_once_with()
        mock_asyncio_writer.close.assert_not_called()
        mock_asyncio_writer.wait_closed.assert_not_awaited()

    async def test____context____close_transport_and_wait_at_end(
        self,
        socket: StreamSocketAdapter,
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
        socket: StreamSocketAdapter,
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
        socket: StreamSocketAdapter,
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
        socket: StreamSocketAdapter,
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
        socket: StreamSocketAdapter,
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
        socket: StreamSocketAdapter,
        mock_asyncio_writer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        await socket.sendall(b"data to send")

        # Assert
        mock_asyncio_writer.write.assert_called_once_with(mocker.ANY)  # cannot test args because it will be a closed memoryview()
        mock_asyncio_writer.drain.assert_awaited_once_with()

    async def test____getsockname____return_sockname_extra_info(
        self,
        socket: StreamSocketAdapter,
        asyncio_writer_extra_info: dict[str, Any],
    ) -> None:
        # Arrange

        # Act
        laddr = socket.get_local_address()

        # Assert
        assert laddr == asyncio_writer_extra_info["sockname"]

    async def test____getpeername____return_peername_extra_info(
        self,
        socket: StreamSocketAdapter,
        asyncio_writer_extra_info: dict[str, Any],
    ) -> None:
        # Arrange

        # Act
        raddr = socket.get_remote_address()

        # Assert
        assert raddr == asyncio_writer_extra_info["peername"]

    async def test____socket____returns_transport_socket(
        self,
        socket: StreamSocketAdapter,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        transport_socket = socket.socket()

        # Assert
        assert transport_socket is mock_tcp_socket


@pytest.mark.asyncio
class TestListenerSocketAdapter(BaseTestStreamSocket):
    @pytest.fixture
    @staticmethod
    def mock_tcp_listener_socket(
        mock_tcp_socket_factory: Callable[[], MagicMock],
        mock_tcp_socket: MagicMock,
    ) -> MagicMock:
        sock = mock_tcp_socket_factory()
        sock.getsockname.return_value = ("127.0.0.1", 11111)
        sock.accept.return_value = (mock_tcp_socket, ("127.0.0.1", 12345))
        return sock

    @pytest.fixture
    @staticmethod
    def mock_stream_socket_adapter_cls(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("easynetwork_asyncio.stream.socket.StreamSocketAdapter", side_effect=StreamSocketAdapter)

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
        return mocker.MagicMock(spec=asyncio.streams.StreamReaderProtocol)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_transport(mocker: MockerFixture) -> MagicMock:
        return mocker.MagicMock(spec=asyncio.Transport)

    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader_protocol_cls(mock_asyncio_reader_protocol: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("asyncio.streams.StreamReaderProtocol", return_value=mock_asyncio_reader_protocol)

    @pytest.fixture
    @staticmethod
    def mock_event_loop_connect_accepted_socket(
        event_loop: asyncio.AbstractEventLoop,
        mocker: MockerFixture,
        mock_asyncio_reader_protocol: MagicMock,
        mock_asyncio_transport: MagicMock,
    ) -> AsyncMock:
        return mocker.patch.object(
            event_loop,
            "connect_accepted_socket",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_transport, mock_asyncio_reader_protocol),
        )

    @pytest.fixture(autouse=True)
    @staticmethod
    def event_loop_sock_accept_replace(event_loop: asyncio.AbstractEventLoop) -> None:
        async def sock_accept(sock: socket.socket) -> tuple[socket.socket, socket._RetAddress]:
            while True:
                try:
                    return sock.accept()
                except BlockingIOError:
                    await asyncio.sleep(0)

        event_loop.sock_accept = sock_accept  # type: ignore[method-assign]

    @staticmethod
    async def _busy_accept_task(
        listener: ListenerSocketAdapter,
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_listener_socket: MagicMock,
    ) -> asyncio.Task[Any]:
        mock_tcp_listener_socket.accept.side_effect = [BlockingIOError, mock_tcp_listener_socket.accept.return_value]
        accept_task = event_loop.create_task(listener.accept())
        while len(mock_tcp_listener_socket.accept.mock_calls) == 0:
            await asyncio.sleep(0)
        mock_tcp_listener_socket.accept.reset_mock()
        return accept_task

    @pytest.fixture(params=[False, True], ids=lambda boolean: f"explicit_listener_loop=={boolean}")
    @staticmethod
    def explicit_listener_loop(request: Any) -> bool:
        return request.param

    @pytest_asyncio.fixture
    @staticmethod
    async def listener(
        request: pytest.FixtureRequest,
        explicit_listener_loop: bool,
        mock_tcp_listener_socket: MagicMock,
    ) -> ListenerSocketAdapter:
        loop: asyncio.AbstractEventLoop | None = None
        if explicit_listener_loop:
            loop = request.getfixturevalue("event_loop")
        return ListenerSocketAdapter(mock_tcp_listener_socket, loop=loop)

    @pytest.mark.usefixtures("listener")
    async def test____dunder_init____ensure_non_blocking_socket(
        self,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act

        # Assert
        mock_tcp_listener_socket.setblocking.assert_called_once_with(False)

    async def test____socket_property____returns_transport_socket(
        self,
        listener: ListenerSocketAdapter,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        socket: asyncio.trsock.TransportSocket = listener.socket()

        # Assert
        assert isinstance(socket, asyncio.trsock.TransportSocket)
        assert getattr(socket, "_sock") is mock_tcp_listener_socket

    async def test____get_local_address____returns_transport_socket(
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

    @pytest.mark.parametrize("abort", [False, True], ids=lambda boolean: f"abort=={boolean}")
    async def test____aclose____close_socket(
        self,
        abort: bool,
        listener: ListenerSocketAdapter,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not listener.is_closing()

        # Act
        if abort:
            await listener.abort()
        else:
            await listener.aclose()

        # Assert
        assert listener.is_closing()
        mock_tcp_listener_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("abort", [False, True], ids=lambda boolean: f"abort=={boolean}")
    async def test____aclose____idempotent(
        self,
        abort: bool,
        listener: ListenerSocketAdapter,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        for _ in range(5):
            if abort:
                await listener.abort()
            else:
                await listener.aclose()

        # Assert
        mock_tcp_listener_socket.close.assert_called_once_with()

    async def test____accept____creates_new_stream_socket(
        self,
        listener: ListenerSocketAdapter,
        event_loop: asyncio.AbstractEventLoop,
        mock_event_loop_connect_accepted_socket: AsyncMock,
        mock_stream_socket_adapter_cls: MagicMock,
        mock_asyncio_reader_protocol: MagicMock,
        mock_asyncio_reader_protocol_cls: MagicMock,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_reader_cls: MagicMock,
        mock_asyncio_reader: MagicMock,
        mock_asyncio_writer_cls: MagicMock,
        mock_asyncio_writer: MagicMock,
        mock_tcp_listener_socket: MagicMock,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        # Act
        socket = await listener.accept()

        # Assert
        assert isinstance(socket, StreamSocketAdapter)
        assert socket.get_remote_address() == ("127.0.0.1", 12345)
        mock_tcp_listener_socket.accept.assert_called_once_with()
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
        mock_stream_socket_adapter_cls.assert_called_once_with(
            mock_asyncio_reader,
            mock_asyncio_writer,
            remote_address=("127.0.0.1", 12345),
        )

    async def test____accept____closed_socket____before_attempt(
        self,
        listener: ListenerSocketAdapter,
        mock_event_loop_connect_accepted_socket: AsyncMock,
        mock_stream_socket_adapter_cls: MagicMock,
        mock_asyncio_reader_protocol_cls: MagicMock,
        mock_asyncio_reader_cls: MagicMock,
        mock_asyncio_writer_cls: MagicMock,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        await listener.abort()

        # Act
        with pytest.raises(OSError):
            await listener.accept()

        # Assert
        mock_tcp_listener_socket.accept.assert_not_called()
        mock_asyncio_reader_cls.assert_not_called()
        mock_asyncio_reader_protocol_cls.assert_not_called()
        mock_event_loop_connect_accepted_socket.assert_not_called()
        mock_asyncio_writer_cls.assert_not_called()
        mock_stream_socket_adapter_cls.assert_not_called()

    async def test____accept____closed_socket____during_attempt(
        self,
        listener: ListenerSocketAdapter,
        event_loop: asyncio.AbstractEventLoop,
        mock_event_loop_connect_accepted_socket: AsyncMock,
        mock_stream_socket_adapter_cls: MagicMock,
        mock_asyncio_reader_protocol_cls: MagicMock,
        mock_asyncio_reader_cls: MagicMock,
        mock_asyncio_writer_cls: MagicMock,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        busy_accept_task: asyncio.Task[Any] = await self._busy_accept_task(listener, event_loop, mock_tcp_listener_socket)

        # Act
        await listener.abort()
        await asyncio.wait([busy_accept_task])

        # Assert
        assert busy_accept_task.cancelled()
        mock_tcp_listener_socket.accept.assert_not_called()
        mock_asyncio_reader_cls.assert_not_called()
        mock_asyncio_reader_protocol_cls.assert_not_called()
        mock_event_loop_connect_accepted_socket.assert_not_called()
        mock_asyncio_writer_cls.assert_not_called()
        mock_stream_socket_adapter_cls.assert_not_called()

    async def test____accept____busy(
        self,
        listener: ListenerSocketAdapter,
        event_loop: asyncio.AbstractEventLoop,
        mock_event_loop_connect_accepted_socket: AsyncMock,
        mock_stream_socket_adapter_cls: MagicMock,
        mock_asyncio_reader_protocol_cls: MagicMock,
        mock_asyncio_reader_cls: MagicMock,
        mock_asyncio_writer_cls: MagicMock,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        from errno import EBUSY

        await self._busy_accept_task(listener, event_loop, mock_tcp_listener_socket)

        # Act
        with pytest.raises(OSError) as exc_info:
            await listener.accept()

        # Assert
        assert exc_info.value.errno == EBUSY
        mock_tcp_listener_socket.accept.assert_not_called()
        mock_asyncio_reader_cls.assert_not_called()
        mock_asyncio_reader_protocol_cls.assert_not_called()
        mock_event_loop_connect_accepted_socket.assert_not_called()
        mock_asyncio_writer_cls.assert_not_called()
        mock_stream_socket_adapter_cls.assert_not_called()
