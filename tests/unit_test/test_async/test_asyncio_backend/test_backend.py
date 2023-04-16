# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from easynetwork_asyncio import AsyncioBackend

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncIOBackend:
    @pytest.fixture
    @staticmethod
    def backend() -> AsyncioBackend:
        return AsyncioBackend()

    @pytest.fixture(params=[("local_address", 12345), None], ids=lambda addr: f"local_address=={addr}")
    @staticmethod
    def local_address(request: Any) -> tuple[str, int] | None:
        return request.param

    @pytest.fixture(params=[("remote_address", 5000)], ids=lambda addr: f"remote_address=={addr}")
    @staticmethod
    def remote_address(request: Any) -> tuple[str, int] | None:
        return request.param

    async def test____coro_yield____use_asyncio_sleep(
        self,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("asyncio.sleep", new_callable=mocker.async_stub)

        # Act
        await backend.coro_yield()

        # Assert
        mock_sleep.assert_awaited_once_with(0)

    async def test____current_time____use_event_loop_time(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_loop_time: MagicMock = mocker.patch.object(event_loop, "time", side_effect=event_loop.time)

        # Act
        current_time = backend.current_time()

        # Assert
        mock_loop_time.assert_called_once_with()
        assert current_time > 0

    async def test____sleep____use_asyncio_sleep(
        self,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("asyncio.sleep", new_callable=mocker.async_stub)

        # Act
        await backend.sleep(mocker.sentinel.delay)

        # Assert
        mock_sleep.assert_awaited_once_with(mocker.sentinel.delay)

    async def test____create_tcp_connection____use_asyncio_open_connection(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.socket.StreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mocker.sentinel.reader, mocker.sentinel.writer),
        )

        # Act
        socket = await backend.create_tcp_connection(
            *remote_address,
            family=1234,
            happy_eyeballs_delay=42,
            local_address=local_address,
        )

        # Assert
        mock_open_connection.assert_awaited_once_with(
            *remote_address,
            family=1234,
            happy_eyeballs_delay=42,
            local_addr=local_address,
            limit=MAX_STREAM_BUFSIZE,
        )
        mock_StreamSocketAdapter.assert_called_once_with(mocker.sentinel.reader, mocker.sentinel.writer)
        assert socket is mocker.sentinel.socket

    @pytest.mark.parametrize(
        ["given_value", "expected_value"],
        [
            pytest.param(None, 0.25, id="use_rfc_value_if_None"),
            pytest.param(float("inf"), float("inf"), id="handle_infinite"),
        ],
    )
    async def test____create_tcp_connection____happy_eyeballs_delay(
        self,
        given_value: float | None,
        expected_value: float | None,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mocker.patch("easynetwork_asyncio.stream.socket.StreamSocketAdapter")
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mocker.sentinel.reader, mocker.sentinel.writer),
        )

        # Act
        await backend.create_tcp_connection(
            *remote_address,
            family=1234,
            happy_eyeballs_delay=given_value,
            local_address=local_address,
        )

        # Assert
        mock_open_connection.assert_awaited_once_with(
            mocker.ANY,  # host: Not tested here
            mocker.ANY,  # port: Not tested here
            happy_eyeballs_delay=expected_value,
            family=mocker.ANY,  # Not tested here
            local_addr=mocker.ANY,  # Not tested here
            limit=mocker.ANY,  # Not tested here
        )

    async def test____wrap_tcp_client_socket____use_asyncio_open_connection(
        self,
        backend: AsyncioBackend,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.socket.StreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mocker.sentinel.reader, mocker.sentinel.writer),
        )

        # Act
        socket = await backend.wrap_tcp_client_socket(mock_tcp_socket)

        # Assert
        mock_open_connection.assert_awaited_once_with(
            sock=mock_tcp_socket,
            limit=MAX_STREAM_BUFSIZE,
        )
        mock_StreamSocketAdapter.assert_called_once_with(mocker.sentinel.reader, mocker.sentinel.writer)
        assert socket is mocker.sentinel.socket
        mock_tcp_socket.setblocking.assert_called_once_with(False)

    @pytest.mark.parametrize("remote_address", [("remote_address", 5000), None], indirect=True)
    async def test____create_udp_endpoint____use_loop_create_datagram_endpoint(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int] | None,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_DatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.socket.DatagramSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.datagram.endpoint.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.endpoint,
        )

        # Act
        socket = await backend.create_udp_endpoint(
            family=1234,
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=True,
        )

        # Assert
        mock_create_datagram_endpoint.assert_awaited_once_with(
            family=1234,
            local_addr=local_address,
            remote_addr=remote_address,
            reuse_port=True,
        )
        mock_DatagramSocketAdapter.assert_called_once_with(mocker.sentinel.endpoint)
        assert socket is mocker.sentinel.socket

    async def test____wrap_udp_socket____use_loop_create_datagram_endpoint(
        self,
        backend: AsyncioBackend,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_DatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.socket.DatagramSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.datagram.endpoint.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.endpoint,
        )

        # Act
        socket = await backend.wrap_udp_socket(mock_udp_socket)

        # Assert
        mock_create_datagram_endpoint.assert_awaited_once_with(socket=mock_udp_socket)
        mock_DatagramSocketAdapter.assert_called_once_with(mocker.sentinel.endpoint)
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

    async def test____create_event____use_asyncio_Event_class(
        self,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_Event = mocker.patch("asyncio.Event", return_value=mocker.sentinel.event)

        # Act
        event = backend.create_event()

        # Assert
        mock_Event.assert_called_once_with()
        assert event is mocker.sentinel.event

    async def test____run_in_thread____use_asyncio_to_thread(
        self,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func_stub = mocker.stub()
        mock_to_thread: AsyncMock = mocker.patch(
            "asyncio.to_thread",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.return_value,
        )

        # Act
        ret_val = await backend.run_in_thread(
            func_stub,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kwargs1,
            kw2=mocker.sentinel.kwargs2,
        )

        # Assert
        mock_to_thread.assert_awaited_once_with(
            func_stub,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kwargs1,
            kw2=mocker.sentinel.kwargs2,
        )
        func_stub.assert_not_called()
        assert ret_val is mocker.sentinel.return_value

    async def test____create_threads_portal____returns_asyncio_portal(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
    ) -> None:
        # Arrange
        from easynetwork_asyncio.threads import ThreadsPortal

        # Act
        threads_portal = backend.create_threads_portal()

        # Assert
        assert isinstance(threads_portal, ThreadsPortal)
        assert threads_portal.loop is event_loop

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
