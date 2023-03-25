# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from easynetwork_asyncio import AsyncioBackend

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncIOBackend:
    @pytest.fixture(scope="class")
    @staticmethod
    def backend() -> AsyncioBackend:
        return AsyncioBackend()

    async def test____coro_yield____use_asyncio_sleep(self, backend: AsyncioBackend, mocker: MockerFixture) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("asyncio.sleep", new_callable=mocker.async_stub)

        # Act
        await backend.coro_yield()

        # Assert
        mock_sleep.assert_awaited_once_with(0)

    async def test____create_tcp_connection____use_asyncio_open_connection(
        self,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.StreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mocker.sentinel.reader, mocker.sentinel.writer),
        )

        # Act
        socket = await backend.create_tcp_connection(
            "remote_address",
            5000,
            happy_eyeballs_delay=42,
            source_address=("local_address", 12345),
        )

        # Assert
        mock_open_connection.assert_awaited_once_with(
            "remote_address",
            5000,
            happy_eyeballs_delay=42,
            local_address=("local_address", 12345),
            limit=MAX_STREAM_BUFSIZE,
        )
        mock_StreamSocketAdapter.assert_called_once_with(backend, mocker.sentinel.reader, mocker.sentinel.writer)
        assert socket is mocker.sentinel.socket

    @pytest.mark.parametrize(
        ["given_value", "expected_value"],
        [
            pytest.param(None, 0.25, id="use_rfc_value_if_None"),
            pytest.param(float("inf"), None, id="give_None_if_infinite"),
        ],
    )
    async def test____create_tcp_connection____happy_eyeballs_delay(
        self,
        given_value: float | None,
        expected_value: float | None,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mocker.patch("easynetwork_asyncio.stream.StreamSocketAdapter")
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mocker.sentinel.reader, mocker.sentinel.writer),
        )

        # Act
        await backend.create_tcp_connection(
            "remote_address",
            5000,
            happy_eyeballs_delay=given_value,
        )

        # Assert
        mock_open_connection.assert_awaited_once_with(
            "remote_address",
            5000,
            happy_eyeballs_delay=expected_value,
            local_address=mocker.ANY,  # Not tested here
            limit=mocker.ANY,  # Not tested here
        )

    async def test____wrap_tcp_socket____use_asyncio_open_connection(
        self,
        backend: AsyncioBackend,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.StreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mocker.sentinel.reader, mocker.sentinel.writer),
        )

        # Act
        socket = await backend.wrap_tcp_socket(mock_tcp_socket)

        # Assert
        mock_open_connection.assert_awaited_once_with(
            sock=mock_tcp_socket,
            limit=MAX_STREAM_BUFSIZE,
        )
        mock_StreamSocketAdapter.assert_called_once_with(backend, mocker.sentinel.reader, mocker.sentinel.writer)
        assert socket is mocker.sentinel.socket
        mock_tcp_socket.setblocking.assert_called_once_with(False)

    async def test____create_udp_endpoint____use_loop_create_datagram_endpoint(
        self,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_DatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.DatagramSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.datagram.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.endpoint,
        )

        # Act
        socket = await backend.create_udp_endpoint(
            local_address=("local_address", 12345),
            remote_address=("remote_address", 5000),
            reuse_port=True,
        )

        # Assert
        mock_create_datagram_endpoint.assert_awaited_once_with(
            local_address=("local_address", 12345),
            remote_address=("remote_address", 5000),
            reuse_port=True,
        )
        mock_DatagramSocketAdapter.assert_called_once_with(backend, mocker.sentinel.endpoint)
        assert socket is mocker.sentinel.socket

    async def test____wrap_udp_socket____use_loop_create_datagram_endpoint(
        self,
        backend: AsyncioBackend,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_DatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.DatagramSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.datagram.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.endpoint,
        )

        # Act
        socket = await backend.wrap_udp_socket(mock_udp_socket)

        # Assert
        mock_create_datagram_endpoint.assert_awaited_once_with(socket=mock_udp_socket)
        mock_DatagramSocketAdapter.assert_called_once_with(backend, mocker.sentinel.endpoint)
        assert socket is mocker.sentinel.socket
        mock_udp_socket.setblocking.assert_called_once_with(False)

    async def test____create_lock____use_asyncio_Lock_class(
        self,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_Lock = mocker.patch("asyncio.Lock", return_value=mocker.sentinel.lock)

        # Act
        lock = backend.create_lock()

        # Assert
        mock_Lock.assert_called_once_with()
        assert lock is mocker.sentinel.lock

    async def test____wait_future____use_asyncio_wrap_future(
        self,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wrap_future: AsyncMock = mocker.patch(
            "asyncio.wrap_future",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.result,
        )

        # Act
        result = await backend.wait_future(mocker.sentinel.future)

        # Assert
        mock_wrap_future.assert_awaited_once_with(mocker.sentinel.future)
        assert result is mocker.sentinel.result
