# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine, Iterator
from errno import EBUSY, ECONNABORTED, EINTR, ENOTSOCK
from socket import SHUT_RD, SHUT_RDWR, SHUT_WR, socket as Socket
from typing import TYPE_CHECKING, Any, final

from easynetwork_asyncio.socket import AsyncSocket

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class BaseTestAsyncSocket:
    @pytest.fixture(autouse=True)
    @classmethod
    def event_loop_sock_method_replace(cls, event_loop: asyncio.AbstractEventLoop, monkeypatch: pytest.MonkeyPatch) -> None:
        to_patch = [
            ("sock_accept", "accept"),
            ("sock_recv", "recv"),
            ("sock_recvfrom", "recvfrom"),
            ("sock_sendall", "send"),
            ("sock_sendto", "sendto"),
        ]

        for event_loop_method, sock_method in to_patch:
            cls.__patch_async_sock_method(event_loop, event_loop_method, sock_method, monkeypatch)

    @staticmethod
    def __patch_async_sock_method(
        event_loop: asyncio.AbstractEventLoop,
        event_loop_method: str,
        sock_method: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def sock_method_patch(sock: Socket, *args: Any, **kwargs: Any) -> Any:
            method: Callable[..., Any] = getattr(sock, sock_method)
            while True:
                try:
                    return method(*args, **kwargs)
                except BlockingIOError:
                    await asyncio.sleep(0)

        monkeypatch.setattr(event_loop, event_loop_method, sock_method_patch)

    @staticmethod
    @contextlib.contextmanager
    def _set_sock_method_in_blocking_state(mock_socket_method: MagicMock) -> Iterator[None]:
        default_side_effect = mock_socket_method.side_effect
        default_return_value = mock_socket_method.return_value
        try:
            mock_socket_method.side_effect = BlockingIOError
            yield
        finally:
            mock_socket_method.configure_mock(side_effect=default_side_effect, return_value=default_return_value)

    @staticmethod
    async def _busy_socket_task(
        coroutine: Coroutine[Any, Any, Any],
        event_loop: asyncio.AbstractEventLoop,
        mock_socket_method: MagicMock,
    ) -> asyncio.Task[Any]:
        accept_task = event_loop.create_task(coroutine)
        async with asyncio.timeout(5):
            while len(mock_socket_method.call_args_list) == 0:
                await asyncio.sleep(0)
        mock_socket_method.reset_mock()
        return accept_task


class MixinTestAsyncSocketBusy(BaseTestAsyncSocket):
    async def test____method____busy(
        self,
        socket_method: Callable[[], Coroutine[Any, Any, Any]],
        event_loop: asyncio.AbstractEventLoop,
        mock_socket_method: MagicMock,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(mock_socket_method):
            _ = await self._busy_socket_task(socket_method(), event_loop, mock_socket_method)

        # Act
        with pytest.raises(OSError) as exc_info:
            await socket_method()

        # Assert
        assert exc_info.value.errno == EBUSY
        mock_socket_method.assert_not_called()

    async def test____method____closed_socket____before_attempt(
        self,
        socket: AsyncSocket,
        socket_method: Callable[[], Coroutine[Any, Any, Any]],
        mock_socket_method: MagicMock,
    ) -> None:
        # Arrange
        await socket.aclose()

        # Act
        with pytest.raises(OSError) as exc_info:
            await socket_method()

        # Assert
        assert exc_info.value.errno == ENOTSOCK
        mock_socket_method.assert_not_called()

    async def test____method____closed_socket____during_attempt(
        self,
        socket: AsyncSocket,
        abort_errno: int,
        socket_method: Callable[[], Coroutine[Any, Any, Any]],
        event_loop: asyncio.AbstractEventLoop,
        mock_socket_method: MagicMock,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(mock_socket_method):
            busy_method_task: asyncio.Task[Any] = await self._busy_socket_task(socket_method(), event_loop, mock_socket_method)

        # Act
        await socket.aclose()
        with pytest.raises(OSError) as exc_info:
            await busy_method_task

        # Assert
        assert exc_info.value.errno == abort_errno
        mock_socket_method.assert_not_called()

    @pytest.mark.parametrize("cancellation_requests", [1, 3])
    async def test____method____external_cancellation_during_attempt(
        self,
        cancellation_requests: int,
        socket_method: Callable[[], Coroutine[Any, Any, Any]],
        event_loop: asyncio.AbstractEventLoop,
        mock_socket_method: MagicMock,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(mock_socket_method):
            busy_method_task: asyncio.Task[Any] = await self._busy_socket_task(socket_method(), event_loop, mock_socket_method)

        # Act
        for _ in range(cancellation_requests):
            busy_method_task.cancel()
        await asyncio.wait([busy_method_task])

        # Assert
        assert busy_method_task.cancelled()
        mock_socket_method.assert_not_called()

    async def test____method____raises_CancelledError(
        self,
        socket_method: Callable[[], Coroutine[Any, Any, Any]],
        event_loop: asyncio.AbstractEventLoop,
        mock_socket_method: MagicMock,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(mock_socket_method):
            busy_method_task: asyncio.Task[Any] = await self._busy_socket_task(socket_method(), event_loop, mock_socket_method)

        mock_socket_method.side_effect = asyncio.CancelledError

        # Act
        await asyncio.wait([busy_method_task])

        # Assert
        mock_socket_method.assert_called()
        assert busy_method_task.cancelled()
        assert busy_method_task.cancelling() == 0


@final
class TestAsyncSocketCommon(BaseTestAsyncSocket):
    @pytest.fixture
    @staticmethod
    def mock_stdlib_socket(mock_socket_factory: Callable[[], MagicMock]) -> MagicMock:
        return mock_socket_factory()

    @pytest.fixture
    @staticmethod
    def socket(
        event_loop: asyncio.AbstractEventLoop,
        mock_stdlib_socket: MagicMock,
    ) -> AsyncSocket:
        return AsyncSocket(mock_stdlib_socket, event_loop)

    @pytest.mark.usefixtures("socket")
    async def test____dunder_init____ensure_non_blocking_socket(
        self,
        mock_stdlib_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act

        # Assert
        mock_stdlib_socket.setblocking.assert_called_once_with(False)

    async def test____socket_property____returns_transport_socket(
        self,
        socket: AsyncSocket,
        mock_stdlib_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        trsock: asyncio.trsock.TransportSocket = socket.socket

        # Assert
        assert isinstance(trsock, asyncio.trsock.TransportSocket)
        assert getattr(trsock, "_sock") is mock_stdlib_socket

    async def test____loop_property____returns_given_event_loop(
        self,
        socket: AsyncSocket,
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        # Arrange

        # Act
        socket_loop = socket.loop

        # Assert
        assert socket_loop is event_loop

    async def test____aclose____close_socket(
        self,
        socket: AsyncSocket,
        mock_stdlib_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not socket.is_closing()

        # Act
        await socket.aclose()

        # Assert
        assert socket.is_closing()
        mock_stdlib_socket.close.assert_called_once_with()

    async def test____aclose____idempotent(
        self,
        socket: AsyncSocket,
        mock_stdlib_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        for _ in range(5):
            await socket.aclose()

        # Assert
        mock_stdlib_socket.close.assert_called_once_with()

    async def test____aclose____used_in_context(
        self,
        socket: AsyncSocket,
        mock_stdlib_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not socket.is_closing()

        # Act
        async with socket:
            assert not socket.is_closing()

        # Assert
        assert socket.is_closing()
        mock_stdlib_socket.close.assert_called_once_with()


class TestAsyncListenerSocket(MixinTestAsyncSocketBusy):
    @pytest.fixture
    @staticmethod
    def mock_tcp_listener_socket(
        mock_tcp_socket_factory: Callable[[], MagicMock],
        mock_tcp_socket: MagicMock,
    ) -> MagicMock:
        sock = mock_tcp_socket_factory()
        sock.accept.return_value = (mock_tcp_socket, ("127.0.0.1", 12345))
        return sock

    @pytest.fixture
    @staticmethod
    def socket(
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_listener_socket: MagicMock,
    ) -> AsyncSocket:
        return AsyncSocket(mock_tcp_listener_socket, event_loop)

    @pytest.fixture
    @staticmethod
    def abort_errno() -> int:
        return EINTR

    @pytest.fixture
    @staticmethod
    def socket_method(socket: AsyncSocket) -> Callable[[], Coroutine[Any, Any, Any]]:
        return lambda: socket.accept()

    @pytest.fixture
    @staticmethod
    def mock_socket_method(mock_tcp_listener_socket: MagicMock) -> MagicMock:
        return mock_tcp_listener_socket.accept

    async def test____accept____returns_socket(
        self,
        socket: AsyncSocket,
        mock_tcp_listener_socket: MagicMock,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client_socket = await socket.accept()

        # Assert
        assert client_socket is mock_tcp_socket
        mock_tcp_listener_socket.accept.assert_called_once_with()


class TestAsyncStreamSocket(MixinTestAsyncSocketBusy):
    @pytest.fixture
    @staticmethod
    def mock_tcp_socket(mock_tcp_socket: MagicMock) -> MagicMock:
        mock_tcp_socket.recv.return_value = b"data"
        mock_tcp_socket.send.side_effect = len
        mock_tcp_socket.shutdown.return_value = None
        return mock_tcp_socket

    @pytest.fixture
    @staticmethod
    def socket(
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_socket: MagicMock,
    ) -> AsyncSocket:
        socket = AsyncSocket(mock_tcp_socket, event_loop)
        mock_tcp_socket.reset_mock()
        return socket

    @pytest.fixture(params=["sendall", "recv"])
    @staticmethod
    def sock_method_name(request: Any) -> str:
        return request.param

    @pytest.fixture
    @staticmethod
    def abort_errno() -> int:
        return ECONNABORTED

    @pytest.fixture
    @staticmethod
    def socket_method(sock_method_name: str, socket: AsyncSocket) -> Callable[[], Coroutine[Any, Any, Any]]:
        match sock_method_name:
            case "sendall":
                return lambda: socket.sendall(b"data")
            case "recv":
                return lambda: socket.recv(1024)
            case _:
                raise SystemError

    @pytest.fixture
    @staticmethod
    def mock_socket_method(sock_method_name: str, mock_tcp_socket: MagicMock) -> MagicMock:
        match sock_method_name:
            case "sendall":
                return mock_tcp_socket.send
            case "recv":
                return mock_tcp_socket.recv
            case _:
                raise SystemError

    @pytest.fixture
    @staticmethod
    def mock_socket_close_method(mock_tcp_socket: MagicMock) -> MagicMock:
        return mock_tcp_socket.close

    async def test____sendall____sends_data_to_stdlib_socket(
        self,
        socket: AsyncSocket,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.sendall(b"data")

        # Assert
        mock_tcp_socket.send.assert_called_once_with(b"data")

    async def test____recv____receives_data_from_stdlib_socket(
        self,
        socket: AsyncSocket,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        data: bytes = await socket.recv(123456789)

        # Assert
        assert data == b"data"
        mock_tcp_socket.recv.assert_called_once_with(123456789)

    @pytest.mark.parametrize(
        "shutdown_how",
        [
            pytest.param(SHUT_RD, id="SHUT_RD"),
            pytest.param(SHUT_WR, id="SHUT_WR"),
            pytest.param(SHUT_RDWR, id="SHUT_RDWR"),
        ],
    )
    async def test____shutdown____calls_socket_shutdown(
        self,
        shutdown_how: int,
        socket: AsyncSocket,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.shutdown(shutdown_how)

        # Assert
        mock_tcp_socket.shutdown.assert_called_once_with(shutdown_how)

    @pytest.mark.parametrize(
        "shutdown_how",
        [
            pytest.param(SHUT_RD, id="SHUT_RD"),
            pytest.param(SHUT_WR, id="SHUT_WR"),
            pytest.param(SHUT_RDWR, id="SHUT_RDWR"),
        ],
    )
    async def test____shutdown____closed_socket(
        self,
        shutdown_how: int,
        socket: AsyncSocket,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        await socket.aclose()

        # Act
        with pytest.raises(OSError) as exc_info:
            await socket.shutdown(shutdown_how)

        # Assert
        assert exc_info.value.errno == ENOTSOCK
        mock_tcp_socket.shutdown.assert_not_called()

    @pytest.mark.parametrize(
        "shutdown_how",
        [
            pytest.param(SHUT_RD, id="SHUT_RD"),
            pytest.param(SHUT_WR, id="SHUT_WR"),
            pytest.param(SHUT_RDWR, id="SHUT_RDWR"),
        ],
    )
    async def test____shutdown____busy_socket_send(
        self,
        shutdown_how: int,
        socket: AsyncSocket,
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(mock_tcp_socket.send):
            _ = await self._busy_socket_task(socket.sendall(b"data"), event_loop, mock_tcp_socket.send)

        # Act
        await socket.shutdown(shutdown_how)

        # Assert
        if shutdown_how == SHUT_RD:
            assert mock_tcp_socket.mock_calls == [
                mocker.call.send(b"data"),
                mocker.call.shutdown(shutdown_how),
                mocker.call.send(b"data"),
            ]
        else:
            assert mock_tcp_socket.mock_calls == [
                mocker.call.send(b"data"),
                mocker.call.send(b"data"),
                mocker.call.shutdown(shutdown_how),
            ]

    @pytest.mark.parametrize(
        "shutdown_how",
        [
            pytest.param(SHUT_RD, id="SHUT_RD"),
            pytest.param(SHUT_WR, id="SHUT_WR"),
            pytest.param(SHUT_RDWR, id="SHUT_RDWR"),
        ],
    )
    async def test____shutdown____busy_socket_recv(
        self,
        shutdown_how: int,
        socket: AsyncSocket,
        event_loop: asyncio.AbstractEventLoop,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(mock_tcp_socket.recv):
            _ = await self._busy_socket_task(socket.recv(1024), event_loop, mock_tcp_socket.recv)

        # Act
        await socket.shutdown(shutdown_how)

        # Assert
        assert mock_tcp_socket.mock_calls == [
            mocker.call.recv(1024),
            mocker.call.shutdown(shutdown_how),
            mocker.call.recv(1024),
        ]


class TestAsyncDatagramSocket(MixinTestAsyncSocketBusy):
    @pytest.fixture
    @staticmethod
    def mock_udp_socket(mock_udp_socket: MagicMock) -> MagicMock:
        mock_udp_socket.recvfrom.return_value = (b"data", ("127.0.0.1", 12345))
        mock_udp_socket.sendto.side_effect = lambda data, address: len(data)
        return mock_udp_socket

    @pytest.fixture
    @staticmethod
    def socket(
        event_loop: asyncio.AbstractEventLoop,
        mock_udp_socket: MagicMock,
    ) -> AsyncSocket:
        return AsyncSocket(mock_udp_socket, event_loop)

    @pytest.fixture(params=["sendto", "recvfrom"])
    @staticmethod
    def sock_method_name(request: Any) -> str:
        return request.param

    @pytest.fixture
    @staticmethod
    def abort_errno() -> int:
        return ECONNABORTED

    @pytest.fixture
    @staticmethod
    def socket_method(sock_method_name: str, socket: AsyncSocket) -> Callable[[], Coroutine[Any, Any, Any]]:
        match sock_method_name:
            case "sendto":
                return lambda: socket.sendto(b"data", ("127.0.0.1", 11111))
            case "recvfrom":
                return lambda: socket.recvfrom(1024)
            case _:
                raise SystemError

    @pytest.fixture
    @staticmethod
    def mock_socket_method(sock_method_name: str, mock_udp_socket: MagicMock) -> MagicMock:
        match sock_method_name:
            case "sendto":
                return mock_udp_socket.sendto
            case "recvfrom":
                return mock_udp_socket.recvfrom
            case _:
                raise SystemError

    @pytest.fixture
    @staticmethod
    def mock_socket_close_method(mock_udp_socket: MagicMock) -> MagicMock:
        return mock_udp_socket.close

    async def test____sendto____sends_data_to_stdlib_socket(
        self,
        socket: AsyncSocket,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await socket.sendto(b"data", ("127.0.0.1", 11111))

        # Assert
        mock_udp_socket.sendto.assert_called_once_with(b"data", ("127.0.0.1", 11111))

    async def test____recvfrom____receives_data_from_stdlib_socket(
        self,
        socket: AsyncSocket,
        mock_udp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        data, address = await socket.recvfrom(123456789)

        # Assert
        assert data == b"data"
        assert address == ("127.0.0.1", 12345)
        mock_udp_socket.recvfrom.assert_called_once_with(123456789)
