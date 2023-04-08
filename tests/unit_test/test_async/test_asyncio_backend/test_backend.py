# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from easynetwork_asyncio import AsyncioBackend

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncIOBackend:
    @pytest_asyncio.fixture
    @staticmethod
    async def backend() -> AsyncioBackend:
        return AsyncioBackend()

    @pytest.fixture(params=[("local_address", 12345), None], ids=lambda addr: f"local_address=={addr}")
    @staticmethod
    def local_address(request: Any) -> tuple[str, int] | None:
        return request.param

    @pytest.fixture(params=[("remote_address", 5000)], ids=lambda addr: f"remote_address=={addr}")
    @staticmethod
    def remote_address(request: Any) -> tuple[str, int] | None:
        return request.param

    async def test____coro_yield____use_asyncio_sleep(self, backend: AsyncioBackend, mocker: MockerFixture) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("asyncio.sleep", new_callable=mocker.async_stub)

        # Act
        await backend.coro_yield()

        # Assert
        mock_sleep.assert_awaited_once_with(0)

    async def test____sleep____use_asyncio_sleep(self, backend: AsyncioBackend, mocker: MockerFixture) -> None:
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

    async def test____wrap_connected_tcp_socket____use_asyncio_open_connection(
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
        socket = await backend.wrap_connected_tcp_socket(mock_tcp_socket)

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

    async def test____run_coroutine_from_thread____use_asyncio_run_coroutine_threadsafe(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        coro_func_stub: AsyncMock = mocker.async_stub()
        coro_func_stub.return_value = mocker.sentinel.return_value
        mock_run_coroutine_threadsafe: MagicMock = mocker.patch(
            "asyncio.run_coroutine_threadsafe",
            side_effect=asyncio.run_coroutine_threadsafe,
        )

        # Act
        ret_val: Any = None

        def test_thread() -> None:
            nonlocal ret_val
            ret_val = backend.run_coroutine_from_thread(
                coro_func_stub,
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kwargs1,
                kw2=mocker.sentinel.kwargs2,
            )

        await asyncio.to_thread(test_thread)

        # Assert
        coro_func_stub.assert_awaited_once_with(
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kwargs1,
            kw2=mocker.sentinel.kwargs2,
        )
        mock_run_coroutine_threadsafe.assert_called_once_with(mocker.ANY, event_loop)
        assert ret_val is mocker.sentinel.return_value

    async def test____run_coroutine_from_thread____error_if_called_from_event_loop_thread(
        self,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func_stub: AsyncMock = mocker.async_stub()
        mock_run_coroutine_threadsafe: MagicMock = mocker.patch("asyncio.run_coroutine_threadsafe")

        # Act
        with pytest.raises(RuntimeError):
            backend.run_coroutine_from_thread(
                func_stub,
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kwargs1,
                kw2=mocker.sentinel.kwargs2,
            )

        # Assert
        func_stub.assert_not_called()
        mock_run_coroutine_threadsafe.assert_not_called()

    async def test____run_sync_threadsafe____use_asyncio_run_coroutine_threadsafe(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func_stub: MagicMock = mocker.stub()
        func_stub.return_value = mocker.sentinel.return_value
        mock_run_coroutine_threadsafe: MagicMock = mocker.patch(
            "asyncio.run_coroutine_threadsafe",
            side_effect=asyncio.run_coroutine_threadsafe,
        )

        # Act
        ret_val: Any = None

        def test_thread() -> None:
            nonlocal ret_val
            ret_val = backend.run_sync_threadsafe(
                func_stub,
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kwargs1,
                kw2=mocker.sentinel.kwargs2,
            )

        await asyncio.to_thread(test_thread)

        # Assert
        func_stub.assert_called_once_with(
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kwargs1,
            kw2=mocker.sentinel.kwargs2,
        )
        mock_run_coroutine_threadsafe.assert_called_once_with(mocker.ANY, event_loop)
        assert ret_val is mocker.sentinel.return_value

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
