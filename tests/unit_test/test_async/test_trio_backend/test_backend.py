from __future__ import annotations

from collections.abc import Callable, Sequence
from socket import AF_INET, AF_INET6, AF_UNSPEC, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM
from typing import TYPE_CHECKING, Any, Final

from easynetwork.lowlevel.api_async.backend._trio.backend import TrioBackend
from easynetwork.lowlevel.api_async.backend.abc import ILock

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


_TRIO_BACKEND_MODULE: Final[str] = "easynetwork.lowlevel.api_async.backend._trio"


@pytest.mark.feature_trio(async_test_auto_mark=True)
class TestTrioBackend:
    @pytest.fixture
    @staticmethod
    def backend() -> TrioBackend:
        return TrioBackend()

    @pytest.fixture(params=[("local_address", 12345), None], ids=lambda addr: f"local_address=={addr}")
    @staticmethod
    def local_address(request: pytest.FixtureRequest) -> tuple[str, int] | None:
        return request.param

    @pytest.fixture(params=[("remote_address", 5000)], ids=lambda addr: f"remote_address=={addr}")
    @staticmethod
    def remote_address(request: pytest.FixtureRequest) -> tuple[str, int] | None:
        return request.param

    async def test____get_cancelled_exc_class____returns_trio_Cancelled(
        self,
        backend: TrioBackend,
    ) -> None:
        # Arrange
        import trio

        # Act & Assert
        assert backend.get_cancelled_exc_class() is trio.Cancelled

    async def test____current_time____use_event_loop_time(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import trio

        mock_current_time: MagicMock = mocker.patch("trio.current_time", side_effect=trio.current_time)

        # Act
        current_time = backend.current_time()

        # Assert
        mock_current_time.assert_called_once_with()
        assert current_time > 0

    async def test____sleep____use_trio_sleep(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_sleep: AsyncMock = mocker.patch("trio.sleep", autospec=True)

        # Act
        await backend.sleep(123456789)

        # Assert
        mock_sleep.assert_awaited_once_with(123456789)

    async def test____get_current_task____compute_task_info(
        self,
        backend: TrioBackend,
    ) -> None:
        # Arrange
        import trio

        current_task = trio.lowlevel.current_task()

        # Act
        task_info = backend.get_current_task()

        # Assert
        assert task_info.id == id(current_task)
        assert task_info.name == current_task.name
        assert task_info.coro is current_task.coro

    async def test____getaddrinfo____use_loop_getaddrinfo(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_trio_getaddrinfo = mocker.patch(
            "trio.socket.getaddrinfo",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.addrinfo_list,
        )

        # Act
        addrinfo_list = await backend.getaddrinfo(
            host=mocker.sentinel.host,
            port=mocker.sentinel.port,
            family=mocker.sentinel.family,
            type=mocker.sentinel.type,
            proto=mocker.sentinel.proto,
            flags=mocker.sentinel.flags,
        )

        # Assert
        assert addrinfo_list is mocker.sentinel.addrinfo_list
        mock_trio_getaddrinfo.assert_awaited_once_with(
            mocker.sentinel.host,
            mocker.sentinel.port,
            family=mocker.sentinel.family,
            type=mocker.sentinel.type,
            proto=mocker.sentinel.proto,
            flags=mocker.sentinel.flags,
        )

    async def test____getnameinfo____use_loop_getnameinfo(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_trio_getnameinfo = mocker.patch(
            "trio.socket.getnameinfo",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.resolved_addr,
        )

        # Act
        resolved_addr = await backend.getnameinfo(
            sockaddr=mocker.sentinel.sockaddr,
            flags=mocker.sentinel.flags,
        )

        # Assert
        assert resolved_addr is mocker.sentinel.resolved_addr
        mock_trio_getnameinfo.assert_awaited_once_with(mocker.sentinel.sockaddr, mocker.sentinel.flags)

    @pytest.mark.parametrize("happy_eyeballs_delay", [None, 42], ids=lambda p: f"happy_eyeballs_delay=={p}")
    async def test____create_tcp_connection____create_trio_stream(
        self,
        happy_eyeballs_delay: float | None,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        backend: TrioBackend,
        mock_tcp_socket: MagicMock,
        mock_trio_tcp_socket: MagicMock,
        mock_trio_socket_stream: MagicMock,
        mock_trio_socket_from_stdlib: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

        mock_trio_socket_stream.socket = mock_trio_tcp_socket
        mock_TrioStreamSocketAdapter: MagicMock = mocker.patch(
            f"{_TRIO_BACKEND_MODULE}.stream.socket.TrioStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_trio_SocketStream = mocker.patch(
            "trio.SocketStream",
            return_value=mock_trio_socket_stream,
        )
        mock_trio_socket_from_stdlib.return_value = mock_trio_tcp_socket
        mock_own_create_connection: AsyncMock = mocker.patch.object(
            TrioDNSResolver,
            "create_stream_connection",
            new_callable=mocker.AsyncMock,
            return_value=mock_tcp_socket,
        )

        expected_happy_eyeballs_delay: float = 0.25
        if happy_eyeballs_delay is not None:
            expected_happy_eyeballs_delay = happy_eyeballs_delay

        # Act
        socket = await backend.create_tcp_connection(
            *remote_address,
            happy_eyeballs_delay=happy_eyeballs_delay,
            local_address=local_address,
        )

        # Assert
        mock_own_create_connection.assert_awaited_once_with(
            backend,
            *remote_address,
            happy_eyeballs_delay=expected_happy_eyeballs_delay,
            local_address=local_address,
        )
        mock_trio_socket_from_stdlib.assert_called_once_with(mock_tcp_socket)
        mock_trio_SocketStream.assert_called_once_with(mock_trio_tcp_socket)
        mock_TrioStreamSocketAdapter.assert_called_once_with(backend, mock_trio_socket_stream)
        assert socket is mocker.sentinel.socket

    async def test____wrap_stream_socket____create_trio_stream(
        self,
        backend: TrioBackend,
        mock_tcp_socket: MagicMock,
        mock_trio_tcp_socket: MagicMock,
        mock_trio_socket_stream: MagicMock,
        mock_trio_socket_from_stdlib: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_trio_socket_stream.socket = mock_trio_tcp_socket
        mock_TrioStreamSocketAdapter: MagicMock = mocker.patch(
            f"{_TRIO_BACKEND_MODULE}.stream.socket.TrioStreamSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_trio_SocketStream = mocker.patch(
            "trio.SocketStream",
            return_value=mock_trio_socket_stream,
        )
        mock_trio_socket_from_stdlib.return_value = mock_trio_tcp_socket

        # Act
        socket = await backend.wrap_stream_socket(mock_tcp_socket)

        # Assert
        mock_trio_socket_from_stdlib.assert_called_once_with(mock_tcp_socket)
        mock_trio_SocketStream.assert_called_once_with(mock_trio_tcp_socket)
        mock_TrioStreamSocketAdapter.assert_called_once_with(backend, mock_trio_socket_stream)
        assert socket is mocker.sentinel.socket

    async def test____create_tcp_listeners____open_listener_sockets(
        self,
        backend: TrioBackend,
        mock_tcp_socket: MagicMock,
        mock_trio_tcp_socket: MagicMock,
        mock_trio_socket_listener: MagicMock,
        mock_trio_socket_from_stdlib: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

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
        mock_resolve_listener_addresses = mocker.patch.object(
            TrioDNSResolver,
            "resolve_listener_addresses",
            new_callable=mocker.AsyncMock,
            return_value=addrinfo_list,
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel._utils.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket],
        )
        mock_trio_socket_from_stdlib.side_effect = [mock_trio_tcp_socket]
        mock_trio_SocketListener: MagicMock = mocker.patch("trio.SocketListener", side_effect=[mock_trio_socket_listener])
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            f"{_TRIO_BACKEND_MODULE}.stream.listener.TrioListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_tcp_listeners(
            remote_host,
            remote_port,
            backlog=123456789,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        mock_resolve_listener_addresses.assert_awaited_once_with(
            backend,
            [remote_host],
            remote_port,
            SOCK_STREAM,
        )
        mock_open_listeners.assert_called_once_with(
            addrinfo_list,
            backlog=123456789,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        mock_trio_socket_from_stdlib.assert_called_once_with(mock_tcp_socket)
        mock_trio_SocketListener.assert_called_once_with(mock_trio_tcp_socket)
        mock_ListenerSocketAdapter.assert_called_once_with(backend, mock_trio_socket_listener)
        assert listener_sockets == [mocker.sentinel.listener_socket]

    @pytest.mark.parametrize("remote_host", [None, "", ["::", "0.0.0.0"]], ids=repr)
    async def test____create_tcp_listeners____bind_to_all_interfaces(
        self,
        remote_host: str | list[str] | None,
        backend: TrioBackend,
        mock_trio_socket_from_stdlib: MagicMock,
        mock_tcp_socket_factory: Callable[[int], MagicMock],
        mock_trio_tcp_socket_factory: Callable[[int], MagicMock],
        mock_trio_socket_listener_factory: Callable[[MagicMock], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

        mock_tcp_socket_ipv4 = mock_tcp_socket_factory(AF_INET)
        mock_tcp_socket_ipv6 = mock_tcp_socket_factory(AF_INET6)
        mock_trio_tcp_socket_ipv4 = mock_trio_tcp_socket_factory(AF_INET)
        mock_trio_tcp_socket_ipv6 = mock_trio_tcp_socket_factory(AF_INET6)
        mock_trio_socket_listener_ipv4 = mock_trio_socket_listener_factory(mock_trio_tcp_socket_ipv4)
        mock_trio_socket_listener_ipv6 = mock_trio_socket_listener_factory(mock_trio_tcp_socket_ipv6)
        remote_port = 5000
        addrinfo_list = [
            (
                AF_INET6,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("::", remote_port),
            ),
            (
                AF_INET,
                SOCK_STREAM,
                IPPROTO_TCP,
                "",
                ("0.0.0.0", remote_port),
            ),
        ]
        mock_resolve_listener_addresses = mocker.patch.object(
            TrioDNSResolver,
            "resolve_listener_addresses",
            new_callable=mocker.AsyncMock,
            return_value=addrinfo_list,
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel._utils.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_tcp_socket_ipv6, mock_tcp_socket_ipv4],
        )
        mock_trio_socket_from_stdlib.side_effect = [mock_trio_tcp_socket_ipv6, mock_trio_tcp_socket_ipv4]
        mock_trio_SocketListener: MagicMock = mocker.patch(
            "trio.SocketListener",
            side_effect=[mock_trio_socket_listener_ipv6, mock_trio_socket_listener_ipv4],
        )
        mock_ListenerSocketAdapter: MagicMock = mocker.patch(
            f"{_TRIO_BACKEND_MODULE}.stream.listener.TrioListenerSocketAdapter",
            side_effect=[mocker.sentinel.listener_socket_ipv6, mocker.sentinel.listener_socket_ipv4],
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_tcp_listeners(
            remote_host,
            remote_port,
            backlog=123456789,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        if isinstance(remote_host, list):
            mock_resolve_listener_addresses.assert_awaited_once_with(
                backend,
                remote_host,
                remote_port,
                SOCK_STREAM,
            )
        else:
            mock_resolve_listener_addresses.assert_awaited_once_with(
                backend,
                [None],
                remote_port,
                SOCK_STREAM,
            )
        mock_open_listeners.assert_called_once_with(
            addrinfo_list,
            backlog=123456789,
            reuse_address=mocker.ANY,  # Determined according to OS
            reuse_port=mocker.sentinel.reuse_port,
        )
        assert mock_trio_socket_from_stdlib.call_args_list == [
            mocker.call(sock) for sock in [mock_tcp_socket_ipv6, mock_tcp_socket_ipv4]
        ]
        assert mock_trio_SocketListener.call_args_list == [
            mocker.call(trio_sock) for trio_sock in [mock_trio_tcp_socket_ipv6, mock_trio_tcp_socket_ipv4]
        ]
        assert mock_ListenerSocketAdapter.call_args_list == [
            mocker.call(backend, listener) for listener in [mock_trio_socket_listener_ipv6, mock_trio_socket_listener_ipv4]
        ]
        assert listener_sockets == [mocker.sentinel.listener_socket_ipv6, mocker.sentinel.listener_socket_ipv4]

    @pytest.mark.parametrize("socket_family", [None, AF_INET, AF_INET6], ids=lambda p: f"family=={p}")
    async def test____create_udp_endpoint____create_datagram_socket(
        self,
        local_address: tuple[str, int] | None,
        remote_address: tuple[str, int],
        socket_family: int | None,
        backend: TrioBackend,
        mock_udp_socket: MagicMock,
        mock_trio_udp_socket: MagicMock,
        mock_trio_socket_from_stdlib: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

        mock_TrioDatagramSocketAdapter: MagicMock = mocker.patch(
            f"{_TRIO_BACKEND_MODULE}.datagram.socket.TrioDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_trio_socket_from_stdlib.return_value = mock_trio_udp_socket
        mock_own_create_connection: AsyncMock = mocker.patch.object(
            TrioDNSResolver,
            "create_datagram_connection",
            new_callable=mocker.AsyncMock,
            return_value=mock_udp_socket,
        )

        # Act
        if socket_family is None:
            socket = await backend.create_udp_endpoint(*remote_address, local_address=local_address)
        else:
            socket = await backend.create_udp_endpoint(*remote_address, local_address=local_address, family=socket_family)

        # Assert
        mock_own_create_connection.assert_awaited_once_with(
            backend,
            *remote_address,
            local_address=local_address,
            family=AF_UNSPEC if socket_family is None else socket_family,
        )
        mock_trio_socket_from_stdlib.assert_called_once_with(mock_udp_socket)
        mock_TrioDatagramSocketAdapter.assert_called_once_with(backend, mock_trio_udp_socket)

        assert socket is mocker.sentinel.socket

    async def test____wrap_connected_datagram_socket____create_datagram_socket(
        self,
        backend: TrioBackend,
        mock_udp_socket: MagicMock,
        mock_trio_udp_socket: MagicMock,
        mock_trio_socket_from_stdlib: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_TrioDatagramSocketAdapter: MagicMock = mocker.patch(
            f"{_TRIO_BACKEND_MODULE}.datagram.socket.TrioDatagramSocketAdapter",
            return_value=mocker.sentinel.socket,
        )
        mock_trio_socket_from_stdlib.return_value = mock_trio_udp_socket

        # Act
        socket = await backend.wrap_connected_datagram_socket(mock_udp_socket)

        # Assert
        mock_trio_socket_from_stdlib.assert_called_once_with(mock_udp_socket)
        mock_TrioDatagramSocketAdapter.assert_called_once_with(backend, mock_trio_udp_socket)

        assert socket is mocker.sentinel.socket

    async def test____create_udp_listeners____open_listener_sockets(
        self,
        backend: TrioBackend,
        mock_udp_socket: MagicMock,
        mock_trio_udp_socket: MagicMock,
        mock_trio_socket_from_stdlib: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

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
        mock_resolve_listener_addresses = mocker.patch.object(
            TrioDNSResolver,
            "resolve_listener_addresses",
            new_callable=mocker.AsyncMock,
            return_value=addrinfo_list,
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel._utils.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_udp_socket],
        )
        mock_trio_socket_from_stdlib.side_effect = [mock_trio_udp_socket]
        mock_DatagramListenerSocketAdapter: MagicMock = mocker.patch(
            f"{_TRIO_BACKEND_MODULE}.datagram.listener.TrioDatagramListenerSocketAdapter",
            return_value=mocker.sentinel.listener_socket,
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_udp_listeners(
            remote_host,
            remote_port,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        mock_resolve_listener_addresses.assert_awaited_once_with(
            backend,
            [remote_host],
            remote_port,
            SOCK_DGRAM,
        )
        mock_open_listeners.assert_called_once_with(
            addrinfo_list,
            backlog=None,
            reuse_address=False,
            reuse_port=mocker.sentinel.reuse_port,
        )
        mock_trio_socket_from_stdlib.assert_not_called()
        mock_DatagramListenerSocketAdapter.assert_called_once_with(backend, mock_udp_socket)
        assert listener_sockets == [mocker.sentinel.listener_socket]

    @pytest.mark.parametrize("remote_host", [None, "", ["::", "0.0.0.0"]], ids=repr)
    async def test____create_udp_listeners____bind_to_all_interfaces(
        self,
        remote_host: str | list[str] | None,
        backend: TrioBackend,
        mock_udp_socket_factory: Callable[[int], MagicMock],
        mock_trio_udp_socket_factory: Callable[[int], MagicMock],
        mock_trio_socket_from_stdlib: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio.dns_resolver import TrioDNSResolver

        mock_udp_socket_ipv4 = mock_udp_socket_factory(AF_INET)
        mock_udp_socket_ipv6 = mock_udp_socket_factory(AF_INET6)
        mock_trio_udp_socket_ipv4 = mock_trio_udp_socket_factory(AF_INET)
        mock_trio_udp_socket_ipv6 = mock_trio_udp_socket_factory(AF_INET6)
        remote_port = 5000
        addrinfo_list = [
            (
                AF_INET6,
                SOCK_DGRAM,
                IPPROTO_UDP,
                "",
                ("::1", remote_port),
            ),
            (
                AF_INET,
                SOCK_DGRAM,
                IPPROTO_UDP,
                "",
                ("127.0.0.1", remote_port),
            ),
        ]
        mock_resolve_listener_addresses = mocker.patch.object(
            TrioDNSResolver,
            "resolve_listener_addresses",
            new_callable=mocker.AsyncMock,
            return_value=addrinfo_list,
        )
        mock_open_listeners = mocker.patch(
            "easynetwork.lowlevel._utils.open_listener_sockets_from_getaddrinfo_result",
            return_value=[mock_udp_socket_ipv6, mock_udp_socket_ipv4],
        )
        mock_trio_socket_from_stdlib.side_effect = [mock_trio_udp_socket_ipv6, mock_trio_udp_socket_ipv4]
        mock_DatagramListenerSocketAdapter: MagicMock = mocker.patch(
            f"{_TRIO_BACKEND_MODULE}.datagram.listener.TrioDatagramListenerSocketAdapter",
            side_effect=[mocker.sentinel.listener_socket_ipv6, mocker.sentinel.listener_socket_ipv4],
        )

        # Act
        listener_sockets: Sequence[Any] = await backend.create_udp_listeners(
            remote_host,
            remote_port,
            reuse_port=mocker.sentinel.reuse_port,
        )

        # Assert
        if isinstance(remote_host, list):
            mock_resolve_listener_addresses.assert_awaited_once_with(
                backend,
                remote_host,
                remote_port,
                SOCK_DGRAM,
            )
        else:
            mock_resolve_listener_addresses.assert_awaited_once_with(
                backend,
                [None],
                remote_port,
                SOCK_DGRAM,
            )
        mock_open_listeners.assert_called_once_with(
            addrinfo_list,
            backlog=None,
            reuse_address=False,
            reuse_port=mocker.sentinel.reuse_port,
        )
        mock_trio_socket_from_stdlib.assert_not_called()
        assert mock_DatagramListenerSocketAdapter.call_args_list == [
            mocker.call(backend, trio_sock) for trio_sock in [mock_udp_socket_ipv6, mock_udp_socket_ipv4]
        ]
        assert listener_sockets == [mocker.sentinel.listener_socket_ipv6, mocker.sentinel.listener_socket_ipv4]

    async def test____create_lock____use_trio_Lock_class(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_Lock = mocker.patch("trio.Lock", return_value=mocker.sentinel.lock)

        # Act
        lock = backend.create_lock()

        # Assert
        mock_Lock.assert_called_once_with()
        assert lock is mocker.sentinel.lock

    async def test____create_fair_lock____returns_custom_lock(
        self,
        backend: TrioBackend,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend._trio._trio_utils import FastFIFOLock

        # Act
        lock = backend.create_fair_lock()

        # Assert
        assert isinstance(lock, FastFIFOLock)

    async def test____create_event____use_trio_Event_class(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_Event = mocker.patch("trio.Event", return_value=mocker.sentinel.event)

        # Act
        event = backend.create_event()

        # Assert
        mock_Event.assert_called_once_with()
        assert event is mocker.sentinel.event

    @pytest.mark.parametrize(
        "use_lock",
        [
            pytest.param(False, id="None"),
            pytest.param(True, id="trio.Lock"),
        ],
    )
    async def test____create_condition_var____use_trio_Condition_class(
        self,
        use_lock: bool,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import trio

        mock_lock: MagicMock | None = None if not use_lock else mocker.NonCallableMagicMock(spec=trio.Lock)
        mock_Condition = mocker.patch("trio.Condition", return_value=mocker.sentinel.condition_var)

        # Act
        condition = backend.create_condition_var(mock_lock)

        # Assert
        if mock_lock is None:
            mock_Condition.assert_called_once_with()
        else:
            mock_Condition.assert_called_once_with(mock_lock)
        assert condition is mocker.sentinel.condition_var

    async def test____create_condition_var____invalid_Lock_type(
        self,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_lock: MagicMock = mocker.NonCallableMagicMock(spec=ILock)
        mock_Condition = mocker.patch("trio.Condition", return_value=mocker.sentinel.condition_var)

        # Act
        with pytest.raises(TypeError, match=r"^lock must be a trio\.Lock$"):
            _ = backend.create_condition_var(mock_lock)

        # Assert
        mock_Condition.assert_not_called()

    @pytest.mark.parametrize("abandon_on_cancel", [False, True], ids=lambda p: f"abandon_on_cancel=={p}")
    async def test____run_in_thread____use_loop_run_in_executor(
        self,
        abandon_on_cancel: bool,
        backend: TrioBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func_stub = mocker.stub()
        mock_run_in_executor = mocker.patch(
            "trio.to_thread.run_sync",
            new_callable=mocker.AsyncMock,
            return_value=mocker.sentinel.return_value,
        )

        # Act
        ret_val = await backend.run_in_thread(
            func_stub,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            abandon_on_cancel=abandon_on_cancel,
        )

        # Assert
        mock_run_in_executor.assert_called_once_with(
            func_stub,
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            abandon_on_cancel=abandon_on_cancel,
        )
        func_stub.assert_not_called()
        assert ret_val is mocker.sentinel.return_value
