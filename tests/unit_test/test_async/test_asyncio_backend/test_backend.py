# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from easynetwork_asyncio import AsyncIOBackend

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncIOBackend:
    @pytest.fixture(scope="class")
    @staticmethod
    def backend() -> AsyncIOBackend:
        return AsyncIOBackend()

    async def test____get_extra_info____running_loop(
        self, backend: AsyncIOBackend, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        # Arrange

        # Act
        loop: Any = backend.get_extra_info("loop")

        # Assert
        assert loop is event_loop

    async def test____get_extra_info____unknown_key(self, backend: AsyncIOBackend, mocker: MockerFixture) -> None:
        # Arrange

        # Act
        loop: Any = backend.get_extra_info("unknown_key", default=mocker.sentinel.default)

        # Assert
        assert loop is mocker.sentinel.default

    async def test____sleep____use_asyncio_sleep(self, backend: AsyncIOBackend, mocker: MockerFixture) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("asyncio.sleep", new_callable=mocker.async_stub)

        # Act
        await backend.sleep(123456789)

        # Assert
        mock_sleep.assert_awaited_once_with(123456789)

    async def test____create_tcp_connection____use_asyncio_open_connection(
        self,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.StreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch("asyncio.open_connection", new_callable=mocker.async_stub)
        mock_open_connection.return_value = (mocker.sentinel.reader, mocker.sentinel.writer)

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
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mocker.patch("easynetwork_asyncio.stream.StreamSocketAdapter")
        mock_open_connection: AsyncMock = mocker.patch("asyncio.open_connection", new_callable=mocker.async_stub)
        mock_open_connection.return_value = (mocker.sentinel.reader, mocker.sentinel.writer)

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
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.StreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch("asyncio.open_connection", new_callable=mocker.async_stub)
        mock_open_connection.return_value = (mocker.sentinel.reader, mocker.sentinel.writer)

        # Act
        socket = await backend.wrap_tcp_socket(mocker.sentinel.stdlib_socket)

        # Assert
        mock_open_connection.assert_awaited_once_with(
            sock=mocker.sentinel.stdlib_socket,
            limit=MAX_STREAM_BUFSIZE,
        )
        mock_StreamSocketAdapter.assert_called_once_with(backend, mocker.sentinel.reader, mocker.sentinel.writer)
        assert socket is mocker.sentinel.socket

    async def test____create_udp_endpoint____use_loop_create_datagram_endpoint(
        self,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_DatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.DatagramSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.datagram.create_datagram_endpoint",
            new_callable=mocker.async_stub,
        )
        mock_create_datagram_endpoint.return_value = mocker.sentinel.endpoint

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
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_DatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.DatagramSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.datagram.create_datagram_endpoint",
            new_callable=mocker.async_stub,
        )
        mock_create_datagram_endpoint.return_value = mocker.sentinel.endpoint

        # Act
        socket = await backend.wrap_udp_socket(mocker.sentinel.stdlib_socket)

        # Assert
        mock_create_datagram_endpoint.assert_awaited_once_with(socket=mocker.sentinel.stdlib_socket)
        mock_DatagramSocketAdapter.assert_called_once_with(backend, mocker.sentinel.endpoint)
        assert socket is mocker.sentinel.socket

    async def test____create_lock____use_asyncio_Lock_class(
        self,
        backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_Lock = mocker.patch("asyncio.Lock", return_value=mocker.sentinel.lock)

        # Act
        lock = backend.create_lock()

        # Assert
        mock_Lock.assert_called_once_with()
        assert lock is mocker.sentinel.lock


class TestAsyncIOBackendWithoutLoop:
    def test____get_extra_info____no_running_loop(self, mocker: MockerFixture) -> None:
        # Arrange
        backend = AsyncIOBackend()

        # Act
        loop: Any = backend.get_extra_info("loop", default=mocker.sentinel.default)

        # Assert
        assert loop is mocker.sentinel.default
