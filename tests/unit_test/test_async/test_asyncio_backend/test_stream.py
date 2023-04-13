# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from easynetwork_asyncio.stream.socket import StreamSocketAdapter

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestStreamSocket:
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
