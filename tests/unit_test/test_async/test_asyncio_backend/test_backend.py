# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Sequence, cast

from easynetwork_asyncio import AsyncioBackend

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncIOBackend:
    @pytest.fixture(params=[False, True], ids=lambda boolean: f"use_asyncio_transport=={boolean}")
    @staticmethod
    def use_asyncio_transport(request: Any) -> bool:
        return request.param

    @pytest.fixture
    @staticmethod
    def backend(use_asyncio_transport: bool) -> AsyncioBackend:
        return AsyncioBackend(transport=use_asyncio_transport)

    @pytest.fixture(params=[("local_address", 12345), None], ids=lambda addr: f"local_address=={addr}")
    @staticmethod
    def local_address(request: Any) -> tuple[str, int] | None:
        return request.param

    @pytest.fixture(params=[("remote_address", 5000)], ids=lambda addr: f"remote_address=={addr}")
    @staticmethod
    def remote_address(request: Any) -> tuple[str, int] | None:
        return request.param

    async def test____use_asyncio_transport____follows_option(
        self,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
    ) -> None:
        assert backend.use_asyncio_transport() == use_asyncio_transport

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

    async def test____get_cancelled_exc_class____returns_asyncio_CancelledError(
        self,
        backend: AsyncioBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert backend.get_cancelled_exc_class() is asyncio.CancelledError

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

    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    async def test____create_tcp_connection____use_asyncio_open_connection(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_asyncio_reader = mock_asyncio_stream_reader_factory()
        mock_asyncio_writer = mock_asyncio_stream_writer_factory()
        mock_StreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.socket.AsyncioTransportStreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_reader, mock_asyncio_writer),
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
        mock_StreamSocketAdapter.assert_called_once_with(mock_asyncio_reader, mock_asyncio_writer)
        assert socket is mocker.sentinel.socket

    @pytest.mark.parametrize("use_asyncio_transport", [True], indirect=True)
    async def test____create_tcp_connection____use_asyncio_open_connection____no_happy_eyeballs_delay(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mocker.patch("easynetwork_asyncio.stream.socket.AsyncioTransportStreamSocketAdapter", return_value=mocker.sentinel.socket)
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_stream_reader_factory(), mock_asyncio_stream_writer_factory()),
        )

        # Act
        await backend.create_tcp_connection(
            *remote_address,
            family=1234,
            happy_eyeballs_delay=None,
            local_address=local_address,
        )

        # Assert
        mock_open_connection.assert_awaited_once_with(
            mocker.ANY,  # host: Not tested here
            mocker.ANY,  # port: Not tested here
            family=mocker.ANY,  # Not tested here
            local_addr=mocker.ANY,  # Not tested here
            limit=mocker.ANY,  # Not tested here
        )

    @pytest.mark.parametrize("use_asyncio_transport", [False], indirect=True)
    async def test____create_tcp_connection____creates_raw_socket_adapter(
        self,
        event_loop: asyncio.AbstractEventLoop,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mock_tcp_socket: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.socket.RawStreamSocketAdapter", return_value=mocker.sentinel.socket
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork_asyncio._utils.create_connection",
            new_callable=mocker.AsyncMock,
            return_value=mock_tcp_socket,
        )

        # Act
        socket = await backend.create_tcp_connection(
            *remote_address,
            family=1234,
            local_address=local_address,
        )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_own_create_connection.assert_awaited_once_with(
            *remote_address,
            event_loop,
            family=1234,
            local_address=local_address,
        )
        mock_RawStreamSocketAdapter.assert_called_once_with(mock_tcp_socket, event_loop)
        assert socket is mocker.sentinel.socket

    @pytest.mark.parametrize("use_asyncio_transport", [False], indirect=True)
    async def test____create_tcp_connection____happy_eyeballs_delay_not_supported(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.socket.RawStreamSocketAdapter", side_effect=AssertionError
        )
        mock_asyncio_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )
        mock_own_create_connection: AsyncMock = mocker.patch(
            "easynetwork_asyncio._utils.create_connection",
            new_callable=mocker.AsyncMock,
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(ValueError, match=r"^'happy_eyeballs_delay' option not supported with transport=False$"):
            await backend.create_tcp_connection(
                *remote_address,
                family=1234,
                happy_eyeballs_delay=42,
                local_address=local_address,
            )

        # Assert
        mock_asyncio_open_connection.assert_not_called()
        mock_own_create_connection.assert_not_called()
        mock_RawStreamSocketAdapter.assert_not_called()

    async def test____wrap_tcp_client_socket____use_asyncio_open_connection(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        mock_asyncio_stream_reader_factory: Callable[[], MagicMock],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.tools.socket import MAX_STREAM_BUFSIZE

        mock_asyncio_reader = mock_asyncio_stream_reader_factory()
        mock_asyncio_writer = mock_asyncio_stream_writer_factory()
        mock_AsyncioTransportStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.socket.AsyncioTransportStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_RawStreamSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.socket.RawStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_open_connection: AsyncMock = mocker.patch(
            "asyncio.open_connection",
            new_callable=mocker.AsyncMock,
            return_value=(mock_asyncio_reader, mock_asyncio_writer),
        )

        # Act
        socket = await backend.wrap_tcp_client_socket(mock_tcp_socket)

        # Assert
        if use_asyncio_transport:
            mock_open_connection.assert_awaited_once_with(
                sock=mock_tcp_socket,
                limit=MAX_STREAM_BUFSIZE,
            )
            mock_AsyncioTransportStreamSocketAdapter.assert_called_once_with(mock_asyncio_reader, mock_asyncio_writer)
            mock_RawStreamSocketAdapter.assert_not_called()
        else:
            mock_open_connection.assert_not_awaited()
            mock_RawStreamSocketAdapter.assert_called_once_with(mock_tcp_socket, event_loop)
            mock_AsyncioTransportStreamSocketAdapter.assert_not_called()
        assert socket is mocker.sentinel.socket
        mock_tcp_socket.setblocking.assert_called_with(False)

    async def test____create_tcp_listeners____open_listener_sockets(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import AI_PASSIVE, SOCK_STREAM

        remote_host, remote_port = "remote_address", 5000
        addrinfo_list = [
            (
                mocker.sentinel.family,
                mocker.sentinel.type,
                mocker.sentinel.proto,
                mocker.sentinel.canonical_name,
                (remote_host, remote_port),
            )
        ]
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=addrinfo_list,
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.tools._utils.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.listener.ListenerSocketAdapter", return_value=mocker.sentinel.listener_socket
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_tcp_listeners(
            remote_host,
            remote_port,
            family=mocker.sentinel.family,
            backlog=mocker.sentinel.backlog,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            remote_host,
            remote_port,
            family=mocker.sentinel.family,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE,
        )
        mock_open_listeners.assert_called_once_with(
            set(addrinfo_list),
            backlog=mocker.sentinel.backlog,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        mock_ListenerSocketAdapter.assert_called_once_with(
            mock_tcp_socket,
            event_loop,
            use_asyncio_transport=use_asyncio_transport,
        )
        assert listener_sockets == [mocker.sentinel.listener_socket]

    @pytest.mark.parametrize("remote_host", [None, ""])
    async def test____create_tcp_listeners____bind_on_any_interfaces(
        self,
        remote_host: str,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import AF_INET, AF_INET6, AF_UNSPEC, AI_PASSIVE, IPPROTO_TCP, SOCK_STREAM

        remote_port = 5000
        addrinfo_list = [
            (
                AF_INET,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("0.0.0.0", remote_port),
            ),
            (
                AF_INET6,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("::", remote_port),
            ),
        ]
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=addrinfo_list,
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.tools._utils.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket, mock_tcp_socket],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.listener.ListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_tcp_listeners(
            remote_host,
            remote_port,
            family=AF_UNSPEC,
            backlog=mocker.sentinel.backlog,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            None,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE,
        )
        mock_open_listeners.assert_called_once_with(
            set(addrinfo_list),
            backlog=mocker.sentinel.backlog,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        assert mock_ListenerSocketAdapter.mock_calls == [
            mocker.call(
                mock_tcp_socket,
                event_loop,
                use_asyncio_transport=use_asyncio_transport,
            )
            for _ in range(2)
        ]
        assert listener_sockets == [mocker.sentinel.listener_socket, mocker.sentinel.listener_socket]

    async def test____create_tcp_listeners____bind_on_several_hosts(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import AF_INET, AF_INET6, AF_UNSPEC, AI_PASSIVE, IPPROTO_TCP, SOCK_STREAM

        remote_hosts = ["0.0.0.0", "::"]
        remote_port = 5000
        addrinfo_list = [
            (
                AF_INET,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("0.0.0.0", remote_port),
            ),
            (
                AF_INET6,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("::", remote_port),
            ),
        ]
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                side_effect=[[info] for info in addrinfo_list],
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.tools._utils.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket, mock_tcp_socket],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.listener.ListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_tcp_listeners(
            remote_hosts,
            remote_port,
            family=AF_UNSPEC,
            backlog=mocker.sentinel.backlog,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        assert mock_getaddrinfo.await_args_list == [
            mocker.call(
                host,
                remote_port,
                family=AF_UNSPEC,
                type=SOCK_STREAM,
                proto=0,
                flags=AI_PASSIVE,
            )
            for host in remote_hosts
        ]
        mock_open_listeners.assert_called_once_with(
            set(addrinfo_list),
            backlog=mocker.sentinel.backlog,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        assert mock_ListenerSocketAdapter.mock_calls == [
            mocker.call(
                mock_tcp_socket,
                event_loop,
                use_asyncio_transport=use_asyncio_transport,
            )
            for _ in range(2)
        ]
        assert listener_sockets == [mocker.sentinel.listener_socket, mocker.sentinel.listener_socket]

    async def test____create_tcp_listeners____error_getaddrinfo_returns_empty_list(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from socket import AF_UNSPEC, AI_PASSIVE, SOCK_STREAM

        remote_host = "remote_address"
        remote_port = 5000
        mock_getaddrinfo: AsyncMock = cast(
            "AsyncMock",
            mocker.patch.object(
                event_loop,
                "getaddrinfo",
                new_callable=mocker.AsyncMock,
                return_value=[],
            ),
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.tools._utils.open_listener_sockets_from_getaddrinfo_result",
            side_effect=AssertionError,
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.stream.listener.ListenerSocketAdapter",
            side_effect=AssertionError,
        )

        # Act
        with pytest.raises(OSError, match=r"getaddrinfo\('remote_address'\) returned empty list"):
            await backend.create_tcp_listeners(
                remote_host,
                remote_port,
                family=AF_UNSPEC,
                backlog=mocker.sentinel.backlog,
                reuse_port=mocker.sentinel.reuse_port,
            )

        # Assert
        mock_getaddrinfo.assert_awaited_once_with(
            remote_host,
            remote_port,
            family=AF_UNSPEC,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE,
        )
        mock_open_listeners.assert_not_called()
        mock_ListenerSocketAdapter.assert_not_called()

    @pytest.mark.parametrize("remote_address", [("remote_address", 5000), None], indirect=True)
    async def test____create_udp_endpoint____use_loop_create_datagram_endpoint(
        self,
        event_loop: asyncio.AbstractEventLoop,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int] | None,
        backend: AsyncioBackend,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
        use_asyncio_transport: bool,
        mock_udp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_endpoint = mock_datagram_endpoint_factory()
        mock_AsyncioTransportDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.socket.AsyncioTransportDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_RawDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.socket.RawDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.datagram.endpoint.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mock_endpoint,
        )
        mock_create_datagram_socket: AsyncMock = mocker.patch(
            "easynetwork_asyncio._utils.create_datagram_socket",
            new_callable=mocker.AsyncMock,
            return_value=mock_udp_socket,
        )

        # Act
        socket = await backend.create_udp_endpoint(
            family=1234,
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=True,
        )

        # Assert
        mock_create_datagram_socket.assert_awaited_once_with(
            loop=event_loop,
            family=1234,
            local_address=local_address,
            remote_address=remote_address,
            reuse_port=True,
        )
        if use_asyncio_transport:
            mock_create_datagram_endpoint.assert_awaited_once_with(socket=mock_udp_socket)
            mock_AsyncioTransportDatagramSocketAdapter.assert_called_once_with(mock_endpoint)
            mock_RawDatagramSocketAdapter.assert_not_called()
        else:
            mock_create_datagram_endpoint.assert_not_awaited()
            mock_RawDatagramSocketAdapter.assert_called_once_with(mock_udp_socket, event_loop)
            mock_AsyncioTransportDatagramSocketAdapter.assert_not_called()

        assert socket is mocker.sentinel.socket
        mock_udp_socket.setblocking.assert_called_with(False)

    async def test____wrap_udp_socket____use_loop_create_datagram_endpoint(
        self,
        event_loop: asyncio.AbstractEventLoop,
        backend: AsyncioBackend,
        use_asyncio_transport: bool,
        mock_udp_socket: MagicMock,
        mock_datagram_endpoint_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_endpoint = mock_datagram_endpoint_factory()
        mock_AsyncioTransportDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.socket.AsyncioTransportDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_RawDatagramSocketAdapter: MagicMock = mocker.patch(
            "easynetwork_asyncio.datagram.socket.RawDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_create_datagram_endpoint: AsyncMock = mocker.patch(
            "easynetwork_asyncio.datagram.endpoint.create_datagram_endpoint",
            new_callable=mocker.AsyncMock,
            return_value=mock_endpoint,
        )

        # Act
        socket = await backend.wrap_udp_socket(mock_udp_socket)

        # Assert
        if use_asyncio_transport:
            mock_create_datagram_endpoint.assert_awaited_once_with(socket=mock_udp_socket)
            mock_AsyncioTransportDatagramSocketAdapter.assert_called_once_with(mock_endpoint)
            mock_RawDatagramSocketAdapter.assert_not_called()
        else:
            mock_create_datagram_endpoint.assert_not_awaited()
            mock_RawDatagramSocketAdapter.assert_called_once_with(mock_udp_socket, event_loop)
            mock_AsyncioTransportDatagramSocketAdapter.assert_not_called()

        assert socket is mocker.sentinel.socket
        mock_udp_socket.setblocking.assert_called_with(False)

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

    async def test____run_in_thread____early_cancel(
        self,
        event_loop: asyncio.AbstractEventLoop,
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
        task = event_loop.create_task(
            backend.run_in_thread(
                func_stub,
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kwargs1,
                kw2=mocker.sentinel.kwargs2,
            )
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Assert
        mock_to_thread.assert_not_awaited()
        func_stub.assert_not_called()

    @pytest.mark.parametrize("max_workers", [None, 1, 99])
    async def test___create_thread_pool_executor____returns_AsyncThreadPoolExecutor_instance(
        self,
        max_workers: int | None,
        backend: AsyncioBackend,
    ) -> None:
        # Arrange
        from easynetwork_asyncio.threads import AsyncThreadPoolExecutor

        # Act
        async with backend.create_thread_pool_executor(max_workers) as executor:
            pass

        # Assert
        assert isinstance(executor, AsyncThreadPoolExecutor)
        if max_workers is None:
            assert executor.get_max_number_of_workers() > 0
        else:
            assert executor.get_max_number_of_workers() == max_workers

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
