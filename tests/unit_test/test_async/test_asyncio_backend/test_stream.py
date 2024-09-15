# mypy: disable_error_code=override

from __future__ import annotations

import asyncio
import asyncio.trsock
import contextlib
import logging
import os
import ssl
from collections.abc import AsyncIterator, Callable, Coroutine
from errno import EBADF, EBUSY, errorcode as errno_errorcode
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.backend._asyncio.stream.listener import (
    AbstractAcceptedSocketFactory,
    AcceptedSocketFactory,
    ListenerSocketAdapter,
)
from easynetwork.lowlevel.api_async.backend._asyncio.stream.socket import (
    AsyncioTransportStreamSocketAdapter,
    StreamReaderBufferedProtocol,
)
from easynetwork.lowlevel.api_async.backend._asyncio.tasks import CancelScope, TaskGroup as AsyncIOTaskGroup
from easynetwork.lowlevel.constants import ACCEPT_CAPACITY_ERRNOS, NOT_CONNECTED_SOCKET_ERRNOS
from easynetwork.lowlevel.socket import SocketAttribute

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

from ....tools import PlatformMarkers
from ..._utils import partial_eq
from ...base import BaseTestSocket
from .base import BaseTestAsyncSocket


class BaseTestTransportStreamSocket(BaseTestSocket):
    @pytest.fixture
    @staticmethod
    def mock_asyncio_reader(mock_asyncio_stream_reader_factory: Callable[[], MagicMock]) -> MagicMock:
        return mock_asyncio_stream_reader_factory()

    @pytest.fixture
    @classmethod
    def mock_tcp_socket(cls, mock_tcp_socket: MagicMock) -> MagicMock:
        cls.set_local_address_to_socket_mock(mock_tcp_socket, mock_tcp_socket.family, ("127.0.0.1", 11111))
        cls.set_remote_address_to_socket_mock(mock_tcp_socket, mock_tcp_socket.family, ("127.0.0.1", 12345))
        return mock_tcp_socket

    @pytest.fixture
    @staticmethod
    def asyncio_transport_extra_info(mock_tcp_socket: MagicMock) -> dict[str, Any]:
        return {
            "socket": mock_tcp_socket,
            "sockname": mock_tcp_socket.getsockname.return_value,
            "peername": mock_tcp_socket.getpeername.return_value,
        }

    @pytest.fixture
    @staticmethod
    def mock_asyncio_transport(asyncio_transport_extra_info: dict[str, Any], mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.Transport)
        mock.can_write_eof.return_value = True
        mock.get_extra_info.side_effect = asyncio_transport_extra_info.get
        mock.is_closing.return_value = False
        return mock

    @pytest.fixture
    @staticmethod
    def asyncio_writer_extra_info(asyncio_transport_extra_info: dict[str, Any]) -> dict[str, Any]:
        return asyncio_transport_extra_info

    @pytest.fixture
    @staticmethod
    def mock_asyncio_writer(
        asyncio_writer_extra_info: dict[str, Any],
        mock_asyncio_stream_writer_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock = mock_asyncio_stream_writer_factory()
        mock.get_extra_info.side_effect = asyncio_writer_extra_info.get
        return mock


class BaseTestTransportWithSSL(BaseTestTransportStreamSocket):
    @pytest.fixture
    @staticmethod
    def mock_ssl_object(mock_ssl_context: MagicMock, mocker: MockerFixture) -> MagicMock:
        mock_ssl_object = mocker.NonCallableMagicMock(spec=ssl.SSLObject)
        mock_ssl_object.context = mock_ssl_context
        mock_ssl_object.getpeercert.return_value = mocker.sentinel.peercert
        mock_ssl_object.cipher.return_value = mocker.sentinel.cipher
        mock_ssl_object.compression.return_value = mocker.sentinel.compression
        mock_ssl_object.version.return_value = mocker.sentinel.tls_version
        return mock_ssl_object

    @pytest.fixture
    @staticmethod
    def add_ssl_extra_to_transport(
        asyncio_transport_extra_info: dict[str, Any],
        mock_ssl_context: MagicMock,
        mock_ssl_object: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        asyncio_transport_extra_info.update(
            {
                "sslcontext": mock_ssl_context,
                "ssl_object": mock_ssl_object,
                "peercert": mocker.sentinel.peercert,
                "cipher": mocker.sentinel.cipher,
                "compression": mocker.sentinel.compression,
            }
        )


@pytest.mark.asyncio
class TestListenerSocketAdapter(BaseTestTransportStreamSocket, BaseTestAsyncSocket):
    @pytest.fixture
    @classmethod
    def mock_tcp_listener_socket(
        cls,
        mock_tcp_socket_factory: Callable[[], MagicMock],
    ) -> MagicMock:
        mock_socket = mock_tcp_socket_factory()
        cls.set_local_address_to_socket_mock(mock_socket, mock_socket.family, ("127.0.0.1", 11111))
        cls.configure_socket_mock_to_raise_ENOTCONN(mock_socket)
        return mock_socket

    @pytest.fixture
    @staticmethod
    def mock_tcp_socket(
        mock_tcp_socket: MagicMock,
        mock_tcp_listener_socket: MagicMock,
    ) -> MagicMock:
        mock_tcp_listener_socket.accept.return_value = (mock_tcp_socket, ("127.0.0.1", 12345))
        return mock_tcp_socket

    @pytest.fixture
    @staticmethod
    def accepted_socket_factory(mocker: MockerFixture) -> MagicMock:
        return mocker.MagicMock(spec=AbstractAcceptedSocketFactory)

    @pytest.fixture
    @staticmethod
    def handler(mocker: MockerFixture) -> AsyncMock:
        handler = mocker.async_stub("handler")
        handler.return_value = None
        return handler

    @pytest_asyncio.fixture
    @staticmethod
    async def listener(
        asyncio_backend: AsyncIOBackend,
        mock_tcp_listener_socket: MagicMock,
        accepted_socket_factory: MagicMock,
    ) -> AsyncIterator[ListenerSocketAdapter[Any]]:
        listener: ListenerSocketAdapter[Any] = ListenerSocketAdapter(
            asyncio_backend,
            mock_tcp_listener_socket,
            accepted_socket_factory,
        )
        async with listener:
            yield listener

    @staticmethod
    def _make_accept_side_effect(
        side_effect: Any,
        mocker: MockerFixture,
        sleep_time: float = 0,
    ) -> Callable[[], Coroutine[Any, Any, MagicMock]]:
        accept_cb = mocker.AsyncMock(side_effect=side_effect)

        async def accept_side_effect() -> MagicMock:
            await asyncio.sleep(sleep_time)
            return await accept_cb()

        return accept_side_effect

    async def test____dunder_init____invalid_socket_type(
        self,
        asyncio_backend: AsyncIOBackend,
        mock_udp_socket: MagicMock,
        accepted_socket_factory: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^A 'SOCK_STREAM' socket is expected$"):
            _ = ListenerSocketAdapter(asyncio_backend, mock_udp_socket, accepted_socket_factory)

    async def test____dunder_init____forbids_ssl_sockets(
        self,
        asyncio_backend: AsyncIOBackend,
        mock_ssl_socket: MagicMock,
        accepted_socket_factory: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
            _ = ListenerSocketAdapter(asyncio_backend, mock_ssl_socket, accepted_socket_factory)

    @pytest.mark.usefixtures("listener")
    async def test____dunder_init____ensure_non_blocking_socket(
        self,
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act

        # Assert
        mock_tcp_listener_socket.setblocking.assert_called_once_with(False)

    async def test____dunder_del____ResourceWarning(
        self,
        asyncio_backend: AsyncIOBackend,
        mock_tcp_listener_socket: MagicMock,
        accepted_socket_factory: MagicMock,
    ) -> None:
        # Arrange
        listener: ListenerSocketAdapter[Any] = ListenerSocketAdapter(
            asyncio_backend,
            mock_tcp_listener_socket,
            accepted_socket_factory,
        )

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed listener .+$"):
            del listener

        mock_tcp_listener_socket.close.assert_called()

    async def test____aclose____close_socket(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        assert not listener.is_closing()

        # Act
        await listener.aclose()

        # Assert
        assert listener.is_closing()
        mock_tcp_listener_socket.close.assert_called_once_with()

    async def test____aclose____idempotent(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        for _ in range(5):
            await listener.aclose()

        # Assert
        mock_tcp_listener_socket.close.assert_called_once_with()

    @pytest.mark.parametrize("external_group", [True, False], ids=lambda p: f"external_group=={p}")
    async def test____serve____default(
        self,
        asyncio_backend: AsyncIOBackend,
        listener: ListenerSocketAdapter[Any],
        external_group: bool,
        accepted_socket_factory: MagicMock,
        handler: AsyncMock,
        mock_tcp_socket_factory: Callable[[], MagicMock],
        mock_stream_socket_adapter_factory: Callable[[], MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        stream = mock_stream_socket_adapter_factory()
        client_socket = mock_tcp_socket_factory()
        accepted_socket_factory.connect.return_value = stream
        mocker.patch.object(
            ListenerSocketAdapter,
            "raw_accept",
            side_effect=self._make_accept_side_effect([client_socket, asyncio.CancelledError], mocker, sleep_time=0.1),
        )

        # Act
        task_group: AsyncIOTaskGroup | None
        async with AsyncIOTaskGroup() if external_group else contextlib.nullcontext() as task_group:  # type: ignore[attr-defined]
            with pytest.raises(asyncio.CancelledError):
                await listener.serve(handler, task_group)

        # Assert
        accepted_socket_factory.connect.assert_awaited_once_with(asyncio_backend, client_socket)
        handler.assert_awaited_once_with(stream)

    @pytest.mark.parametrize(
        "exc",
        [
            *(OSError(errno, os.strerror(errno)) for errno in sorted(NOT_CONNECTED_SOCKET_ERRNOS)),
            Exception(),
            asyncio.CancelledError(),
            BaseException(),
        ],
        ids=repr,
    )
    async def test____serve____connect____error_raised(
        self,
        exc: BaseException,
        asyncio_backend: AsyncIOBackend,
        listener: ListenerSocketAdapter[Any],
        accepted_socket_factory: MagicMock,
        handler: AsyncMock,
        mock_tcp_socket_factory: Callable[[], MagicMock],
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.INFO)
        client_socket = mock_tcp_socket_factory()
        accepted_socket_factory.connect.side_effect = exc
        mocker.patch.object(
            ListenerSocketAdapter,
            "raw_accept",
            side_effect=self._make_accept_side_effect([client_socket, asyncio.CancelledError], mocker),
        )

        # Act
        with pytest.raises(BaseExceptionGroup) if type(exc) is BaseException else contextlib.nullcontext():
            async with AsyncIOTaskGroup() as task_group:
                with pytest.raises(asyncio.CancelledError):
                    await listener.serve(handler, task_group)

        # Assert
        accepted_socket_factory.connect.assert_awaited_once_with(asyncio_backend, client_socket)
        handler.assert_not_awaited()
        client_socket.close.assert_called_once_with()

        match exc:
            case asyncio.CancelledError():
                assert len(caplog.records) == 0
                accepted_socket_factory.log_connection_error.assert_not_called()
            case OSError(errno=errno) if errno in NOT_CONNECTED_SOCKET_ERRNOS:
                # ENOTCONN error should not create a big Traceback error but only a warning (at least)
                assert len(caplog.records) == 1
                assert caplog.records[0].levelno == logging.WARNING
                assert caplog.records[0].message == "A client connection was interrupted just after listener.accept()"
                assert caplog.records[0].exc_info is None
            case _:
                assert len(caplog.records) == 0
                accepted_socket_factory.log_connection_error.assert_called_once_with(
                    mocker.ANY,  # logger
                    exc,
                )

    @PlatformMarkers.skipif_platform_win32_because("test failures are all too frequent on CI", skip_only_on_ci=True)
    @pytest.mark.parametrize("errno_value", sorted(ACCEPT_CAPACITY_ERRNOS), ids=errno_errorcode.__getitem__)
    @pytest.mark.flaky(retries=3, delay=0.1)
    async def test____accept____accept_capacity_error(
        self,
        errno_value: int,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)
        mock_tcp_listener_socket.accept.side_effect = OSError(errno_value, os.strerror(errno_value))

        # Act
        # It retries every 100 ms, so in 975 ms it will retry at 0, 100, ..., 900
        # = 10 times total
        with CancelScope(deadline=asyncio.get_running_loop().time() + 0.975):
            await listener.raw_accept()

        # Assert
        assert len(caplog.records) == 10
        for record in caplog.records:
            assert "retrying" in record.message
            assert (
                record.exc_info is not None
                and isinstance(record.exc_info[1], OSError)
                and record.exc_info[1].errno == errno_value
            )

    async def test____accept____reraise_other_OSErrors(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)
        exc = OSError()
        mock_tcp_listener_socket.accept.side_effect = exc

        # Act
        with pytest.raises(OSError) as exc_info:
            await listener.raw_accept()

        # Assert
        assert len(caplog.records) == 0
        assert exc_info.value is exc

    async def test____accept____returns_socket(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        client_socket = await listener.raw_accept()

        # Assert
        assert client_socket is mock_tcp_socket
        mock_tcp_listener_socket.accept.assert_called_once_with()

    async def test____accept____busy(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
        mock_tcp_socket_factory: Callable[[], MagicMock],
    ) -> None:
        # Arrange
        mock_tcp_listener_socket.accept.return_value = (mock_tcp_socket_factory(), ("127.0.0.1", 12345))
        with self._set_sock_method_in_blocking_state(mock_tcp_listener_socket.accept):
            _ = await self._busy_socket_task(listener.raw_accept(), mock_tcp_listener_socket.accept)

        # Act
        with pytest.raises(OSError) as exc_info:
            await listener.raw_accept()

        # Assert
        assert exc_info.value.errno == EBUSY
        mock_tcp_listener_socket.accept.assert_not_called()

    async def test____accept____closed_socket____before_attempt(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        await listener.aclose()

        # Act
        with pytest.raises(OSError) as exc_info:
            await listener.raw_accept()

        # Assert
        assert exc_info.value.errno == EBADF
        mock_tcp_listener_socket.accept.assert_not_called()

    async def test____accept____closed_socket____during_attempt(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(mock_tcp_listener_socket.accept):
            busy_method_task = await self._busy_socket_task(listener.raw_accept(), mock_tcp_listener_socket.accept)

        # Act
        await listener.aclose()
        with pytest.raises(OSError) as exc_info:
            await busy_method_task

        # Assert
        assert exc_info.value.errno == EBADF
        mock_tcp_listener_socket.accept.assert_not_called()

    @pytest.mark.parametrize("errno_value", sorted(ACCEPT_CAPACITY_ERRNOS), ids=errno_errorcode.__getitem__)
    async def test____accept____closed_socket____during_capacity_error_sleep_time(
        self,
        errno_value: int,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(
            mock_tcp_listener_socket.accept,
            exception=OSError(errno_value, os.strerror(errno_value)),
        ):
            busy_method_task = await self._busy_socket_task(listener.raw_accept(), mock_tcp_listener_socket.accept)

        # Act
        await listener.aclose()
        with pytest.raises(OSError) as exc_info:
            await busy_method_task

        # Assert
        assert exc_info.value.errno == EBADF
        mock_tcp_listener_socket.accept.assert_not_called()

    @pytest.mark.parametrize("cancellation_requests", [1, 3])
    async def test____accept____external_cancellation_during_attempt(
        self,
        cancellation_requests: int,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(mock_tcp_listener_socket.accept):
            busy_method_task = await self._busy_socket_task(listener.raw_accept(), mock_tcp_listener_socket.accept)

        # Act
        for _ in range(cancellation_requests):
            busy_method_task.cancel()
        await asyncio.wait([busy_method_task])

        # Assert
        assert busy_method_task.cancelled()
        mock_tcp_listener_socket.accept.assert_not_called()

    async def test____accept____raises_CancelledError(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
    ) -> None:
        # Arrange
        with self._set_sock_method_in_blocking_state(mock_tcp_listener_socket.accept):
            busy_method_task = await self._busy_socket_task(listener.raw_accept(), mock_tcp_listener_socket.accept)

        mock_tcp_listener_socket.accept.side_effect = asyncio.CancelledError

        # Act
        await asyncio.wait([busy_method_task])

        # Assert
        mock_tcp_listener_socket.accept.assert_called()
        assert busy_method_task.cancelled()
        assert busy_method_task.cancelling() == 0

    async def test____get_backend____returns_linked_instance(
        self,
        listener: ListenerSocketAdapter[Any],
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert listener.backend() is asyncio_backend

    async def test____extra_attributes____returns_socket_info(
        self,
        listener: ListenerSocketAdapter[Any],
        mock_tcp_listener_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act & Assert
        trsock = listener.extra(SocketAttribute.socket)
        assert isinstance(trsock, asyncio.trsock.TransportSocket)
        assert getattr(trsock, "_sock") is mock_tcp_listener_socket
        assert listener.extra(SocketAttribute.family) == mock_tcp_listener_socket.family
        assert listener.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert listener.extra(SocketAttribute.peername, mocker.sentinel.no_value) is mocker.sentinel.no_value


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::ResourceWarning")
class TestAcceptedSocketFactory(BaseTestTransportStreamSocket):
    @pytest.fixture
    @staticmethod
    def mock_asyncio_protocol(mocker: MockerFixture, event_loop: asyncio.AbstractEventLoop) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=StreamReaderBufferedProtocol)
        # Currently, _get_close_waiter() is a synchronous function returning a Future, but it will be awaited so this works
        mock._get_close_waiter = mocker.AsyncMock()
        mock._get_loop.return_value = event_loop
        return mock

    @pytest.fixture
    @staticmethod
    def mock_event_loop_connect_accepted_socket(
        event_loop: asyncio.AbstractEventLoop,
        mocker: MockerFixture,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> AsyncMock:
        async def side_effect(protocol_factory: Callable[[], asyncio.Protocol], sock: Any, *args: Any, **kwargs: Any) -> Any:
            protocol_factory()
            return mock_asyncio_transport, mock_asyncio_protocol

        return mocker.patch.object(
            event_loop,
            "connect_accepted_socket",
            new_callable=mocker.AsyncMock,
            side_effect=side_effect,
        )

    @pytest.fixture
    @staticmethod
    def accepted_socket() -> AcceptedSocketFactory:
        return AcceptedSocketFactory()

    async def test____log_connection_error____error_log(
        self,
        caplog: pytest.LogCaptureFixture,
        accepted_socket: AcceptedSocketFactory,
    ) -> None:
        # Arrange
        logger = logging.getLogger(__name__)
        caplog.set_level(logging.ERROR, logger.name)
        exc = BaseException()

        # Act
        accepted_socket.log_connection_error(logger, exc)

        # Assert
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].message == "Error in client task"
        assert caplog.records[0].exc_info is not None and caplog.records[0].exc_info[1] is exc

    async def test____connect____creates_new_stream_socket(
        self,
        asyncio_backend: AsyncIOBackend,
        accepted_socket: AcceptedSocketFactory,
        mock_event_loop_connect_accepted_socket: AsyncMock,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()

        # Act
        socket = await accepted_socket.connect(asyncio_backend, mock_tcp_socket)

        # Assert
        assert isinstance(socket, AsyncioTransportStreamSocketAdapter)
        mock_event_loop_connect_accepted_socket.assert_awaited_once_with(
            partial_eq(StreamReaderBufferedProtocol, loop=event_loop),
            mock_tcp_socket,
        )


@pytest.mark.asyncio
class TestAsyncioTransportStreamSocketAdapter(BaseTestTransportWithSSL):
    @pytest.fixture
    @staticmethod
    def mock_asyncio_protocol(mocker: MockerFixture, event_loop: asyncio.AbstractEventLoop) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=StreamReaderBufferedProtocol)
        # Currently, _get_close_waiter() is a synchronous function returning a Future, but it will be awaited so this works
        mock._get_close_waiter = mocker.AsyncMock()
        mock._get_loop.return_value = event_loop
        return mock

    @pytest_asyncio.fixture
    @staticmethod
    async def socket(
        asyncio_backend: AsyncIOBackend,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> AsyncIterator[AsyncioTransportStreamSocketAdapter]:
        transport = AsyncioTransportStreamSocketAdapter(asyncio_backend, mock_asyncio_transport, mock_asyncio_protocol)
        async with transport:
            yield transport

    @pytest.mark.usefixtures("add_ssl_extra_to_transport")
    async def test____dunder_init____refuse_transports_over_ssl(
        self,
        asyncio_backend: AsyncIOBackend,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(NotImplementedError):
            _ = AsyncioTransportStreamSocketAdapter(asyncio_backend, mock_asyncio_transport, mock_asyncio_protocol)

    async def test____dunder_del____ResourceWarning(
        self,
        asyncio_backend: AsyncIOBackend,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        transport = AsyncioTransportStreamSocketAdapter(asyncio_backend, mock_asyncio_transport, mock_asyncio_protocol)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed transport .+$"):
            del transport

        mock_asyncio_transport.close.assert_called()

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    @pytest.mark.parametrize("can_write_eof", [False, True], ids=lambda p: f"can_write_eof=={p}")
    @pytest.mark.parametrize("wait_close_raise_error", [False, True], ids=lambda p: f"wait_close_raise_error=={p}")
    @pytest.mark.parametrize("write_eof_raise_error", [False, True], ids=lambda p: f"write_eof_raise_error=={p}")
    async def test____aclose____close_transport_and_wait(
        self,
        transport_is_closing: bool,
        can_write_eof: bool,
        wait_close_raise_error: bool,
        write_eof_raise_error: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.return_value = transport_is_closing
        mock_asyncio_transport.can_write_eof.return_value = can_write_eof
        if wait_close_raise_error:
            mock_asyncio_protocol._get_close_waiter.side_effect = OSError
        if write_eof_raise_error:
            mock_asyncio_transport.write_eof.side_effect = OSError

        # Act
        await socket.aclose()
        mock_asyncio_protocol._get_close_waiter.side_effect = None

        # Assert
        if transport_is_closing:
            mock_asyncio_transport.close.assert_not_called()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
            mock_asyncio_transport.abort.assert_not_called()
            mock_asyncio_transport.write_eof.assert_not_called()
        else:
            if can_write_eof:
                mock_asyncio_transport.write_eof.assert_called_once_with()
            else:
                mock_asyncio_transport.write_eof.assert_not_called()
            mock_asyncio_transport.close.assert_called_once_with()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
            mock_asyncio_transport.abort.assert_not_called()

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____aclose____abort_transport_if_cancelled(
        self,
        transport_is_closing: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.return_value = transport_is_closing
        mock_asyncio_protocol._get_close_waiter.side_effect = asyncio.CancelledError

        # Act
        with pytest.raises(asyncio.CancelledError):
            await socket.aclose()
        mock_asyncio_protocol._get_close_waiter.side_effect = None

        # Assert
        if transport_is_closing:
            mock_asyncio_transport.close.assert_not_called()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        else:
            mock_asyncio_transport.close.assert_called_once_with()
            mock_asyncio_protocol._get_close_waiter.assert_awaited_once_with()
        mock_asyncio_transport.abort.assert_not_called()

    @pytest.mark.parametrize("transport_closed", [False, True], ids=lambda p: f"transport_closed=={p}")
    async def test____is_closing____return_internal_flag(
        self,
        transport_closed: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        if transport_closed:
            await socket.aclose()
            mock_asyncio_transport.reset_mock()

        # Act
        state = socket.is_closing()

        # Assert
        mock_asyncio_transport.is_closing.assert_not_called()
        assert state is transport_closed

    async def test____recv____read_from_reader(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_protocol.receive_data.return_value = b"data"

        # Act
        data: bytes = await socket.recv(1024)

        # Assert
        mock_asyncio_protocol.receive_data.assert_awaited_once_with(1024)
        assert data == b"data"

    async def test____recv____null_bufsize(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_protocol.receive_data.return_value = b""

        # Act
        data: bytes = await socket.recv(0)

        # Assert
        mock_asyncio_protocol.receive_data.assert_awaited_once_with(0)
        assert data == b""

    async def test____recv_into____read_from_reader(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_protocol.receive_data_into.return_value = 4
        buffer = bytearray(4)

        # Act
        nbytes = await socket.recv_into(buffer)

        # Assert
        mock_asyncio_protocol.receive_data_into.assert_awaited_once_with(buffer)
        assert nbytes == 4

    async def test____recv_into____null_buffer(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_protocol.receive_data_into.return_value = 0
        buffer = bytearray()

        # Act
        nbytes = await socket.recv_into(buffer)

        # Assert
        mock_asyncio_protocol.receive_data_into.assert_awaited_once_with(buffer)
        assert nbytes == 0

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____send_all____write_and_drain(
        self,
        transport_is_closing: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.is_closing.side_effect = [transport_is_closing]

        # Act
        await socket.send_all(b"data to send")

        # Assert
        mock_asyncio_transport.write.assert_called_once_with(b"data to send")
        mock_asyncio_transport.writelines.assert_not_called()
        mock_asyncio_protocol.writer_drain.assert_awaited_once_with()

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____send_all_from_iterable____writelines_and_drain(
        self,
        transport_is_closing: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_transport: MagicMock,
        mock_asyncio_protocol: MagicMock,
    ) -> None:
        # Arrange
        written_chunks: list[bytes] = []
        mock_asyncio_transport.is_closing.side_effect = [transport_is_closing]
        mock_asyncio_transport.writelines.side_effect = written_chunks.extend

        # Act
        await socket.send_all_from_iterable([b"data", b"to", b"send"])

        # Assert
        mock_asyncio_transport.write.assert_not_called()
        mock_asyncio_transport.writelines.assert_called_once()
        mock_asyncio_protocol.writer_drain.assert_awaited_once_with()
        assert written_chunks == [b"data", b"to", b"send"]

    @pytest.mark.parametrize("can_write_eof", [False, True], ids=lambda p: f"can_write_eof=={p}")
    async def test____send_eof____write_eof(
        self,
        can_write_eof: bool,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_asyncio_transport.can_write_eof.return_value = can_write_eof
        mock_asyncio_transport.write_eof.return_value = None

        # Act & Assert
        if can_write_eof:
            await socket.send_eof()
            mock_asyncio_transport.write_eof.assert_called_once_with()
        else:
            with pytest.raises(UnsupportedOperation):
                await socket.send_eof()
            mock_asyncio_transport.write_eof.assert_not_called()

    async def test____get_backend____returns_linked_instance(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert socket.backend() is asyncio_backend

    async def test____extra_attributes____returns_socket_info(
        self,
        socket: AsyncioTransportStreamSocketAdapter,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert socket.extra(SocketAttribute.socket) is mock_tcp_socket
        assert socket.extra(SocketAttribute.family) == mock_tcp_socket.family
        assert socket.extra(SocketAttribute.sockname) == ("127.0.0.1", 11111)
        assert socket.extra(SocketAttribute.peername) == ("127.0.0.1", 12345)


_ProtocolDataReceiver: TypeAlias = Callable[[StreamReaderBufferedProtocol, int], Coroutine[Any, Any, bytes]]


class TestStreamReaderBufferedProtocol(BaseTestTransportWithSSL):
    @pytest.fixture(autouse=True)
    @staticmethod
    def reduce_protocol_buffer_size(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(StreamReaderBufferedProtocol, "max_size", 16 * 1024)

    @pytest.fixture
    @staticmethod
    def protocol(
        event_loop: asyncio.AbstractEventLoop,
        mock_asyncio_transport: MagicMock,
    ) -> StreamReaderBufferedProtocol:
        protocol = StreamReaderBufferedProtocol(loop=event_loop)
        protocol.connection_made(mock_asyncio_transport)
        return protocol

    @pytest.fixture(params=["data", "buffer"])
    @staticmethod
    def data_receiver(request: pytest.FixtureRequest) -> _ProtocolDataReceiver:
        match request.param:
            case "data":

                async def data_receiver(protocol: StreamReaderBufferedProtocol, bufsize: int, /) -> bytes:
                    return await protocol.receive_data(bufsize)

            case "buffer":

                async def data_receiver(protocol: StreamReaderBufferedProtocol, bufsize: int, /) -> bytes:
                    assert bufsize >= 0
                    with memoryview(bytearray(bufsize)) as buffer:
                        nbytes = await protocol.receive_data_into(buffer)
                        assert nbytes >= 0
                        return bytes(buffer[:nbytes])

            case _:
                pytest.fail("Invalid fixture param")

        return data_receiver

    @staticmethod
    def write_in_protocol_buffer(protocol: asyncio.BufferedProtocol, data: bytes) -> None:
        with memoryview(protocol.get_buffer(-1)).cast("B") as buffer:
            if not data:
                written = 0
            elif buffer.nbytes < len(data):
                written = buffer.nbytes
                buffer[:] = data[:written]
            else:
                written = len(data)
                buffer[:written] = data
        protocol.buffer_updated(written)

    @staticmethod
    def write_eof_in_protocol_buffer(protocol: asyncio.BufferedProtocol) -> bool | None:
        with memoryview(protocol.get_buffer(-1)):
            pass
        return protocol.eof_received()

    @pytest.mark.asyncio
    async def test____dunder_init____use_running_loop(self) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()

        # Act
        protocol = StreamReaderBufferedProtocol()

        # Assert
        assert protocol._get_loop() is event_loop

    def test____dunder_init____use_running_loop____not_in_asyncio_loop(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(RuntimeError):
            _ = StreamReaderBufferedProtocol()

    def test____connection_lost____by_closed_transport(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        close_waiter = protocol._get_close_waiter()
        assert not close_waiter.done()

        # Act
        protocol.connection_lost(None)
        protocol.connection_lost(None)  # Double call must not change anything

        # Assert
        assert close_waiter.done() and close_waiter.exception() is None and close_waiter.result() is None
        mock_asyncio_transport.close.assert_not_called()

        with pytest.raises(BufferError):
            protocol.get_buffer(-1)

    def test____connection_lost____close_waiter_done(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        close_waiter = protocol._get_close_waiter()
        close_waiter.cancel()
        assert close_waiter.done()

        # Act
        protocol.connection_lost(None)

        # Assert
        mock_asyncio_transport.close.assert_not_called()

        with pytest.raises(BufferError):
            protocol.get_buffer(-1)

    def test____connection_lost____by_unrelated_error(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        exception = OSError("Something bad happen")

        close_waiter = protocol._get_close_waiter()
        assert not close_waiter.done()

        # Act
        protocol.connection_lost(exception)
        protocol.connection_lost(exception)  # Double call must not change anything

        # Assert
        assert close_waiter.done() and close_waiter.exception() is None
        mock_asyncio_transport.close.assert_not_called()

    def test____eof_received____returns_True(
        self,
        protocol: StreamReaderBufferedProtocol,
    ) -> None:
        # Arrange

        # Act & Assert
        assert protocol.eof_received() is True

    @pytest.mark.usefixtures("add_ssl_extra_to_transport")
    def test____eof_received____returns_False_for_ssl_transport(
        self,
        protocol: StreamReaderBufferedProtocol,
    ) -> None:
        # Arrange

        # Act & Assert
        assert protocol.eof_received() is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blocking", [False, True], ids=lambda p: f"blocking=={p}")
    async def test____receive_data____default(
        self,
        blocking: bool,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()
        if blocking:
            event_loop.call_later(0.5, self.write_in_protocol_buffer, protocol, b"abcdef")
        else:
            self.write_in_protocol_buffer(protocol, b"abcdef")

        # Act
        data = await data_receiver(protocol, 1024)

        # Assert
        assert data == b"abcdef"
        mock_asyncio_transport.resume_reading.assert_not_called()

    @pytest.mark.asyncio
    async def test____receive_data____partial_read(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        self.write_in_protocol_buffer(protocol, b"abcdef")

        # Act
        first = await data_receiver(protocol, 3)
        second = await data_receiver(protocol, 3)

        # Assert
        assert first == b"abc"
        assert second == b"def"
        mock_asyncio_transport.resume_reading.assert_not_called()

    @pytest.mark.asyncio
    async def test____receive_data____buffer_updated_several_times(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()
        event_loop.call_soon(self.write_in_protocol_buffer, protocol, b"abc")
        event_loop.call_soon(self.write_in_protocol_buffer, protocol, b"def")

        # Act
        data = await data_receiver(protocol, 1024)

        # Assert
        assert data == b"abcdef"
        mock_asyncio_transport.resume_reading.assert_not_called()

    @pytest.mark.asyncio
    async def test____receive_data____null_bufsize(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange

        # Act
        data = await data_receiver(protocol, 0)

        # Assert
        assert data == b""
        mock_asyncio_transport.resume_reading.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("eof_reason", ["eof_received", "connection_lost"])
    @pytest.mark.parametrize("blocking", [False, True], ids=lambda p: f"blocking=={p}")
    async def test____receive_data____eof(
        self,
        blocking: bool,
        eof_reason: Literal["eof_received", "connection_lost"],
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()

        def protocol_eof_handler() -> None:
            match eof_reason:
                case "eof_received":
                    keep_open = self.write_eof_in_protocol_buffer(protocol)
                    assert keep_open is True
                case "connection_lost":
                    protocol.connection_lost(None)
                case _:
                    pytest.fail("Invalid argument")

        if blocking:
            event_loop.call_later(0.5, protocol_eof_handler)
        else:
            protocol_eof_handler()

        # Act
        data = await data_receiver(protocol, 1024)

        # Assert
        assert data == b""
        mock_asyncio_transport.resume_reading.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blocking", [False, True], ids=lambda p: f"blocking=={p}")
    async def test____receive_data____connection_lost_by_unrelated_error(
        self,
        blocking: bool,
        protocol: StreamReaderBufferedProtocol,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()
        exception = OSError("Something bad happen")
        if blocking:
            event_loop.call_later(0.5, protocol.connection_lost, exception)
        else:
            protocol.connection_lost(exception)

        # Act & Assert
        with pytest.raises(OSError) as exc_info:
            _ = await data_receiver(protocol, 1024)

        assert exc_info.value is exception

    @pytest.mark.asyncio
    async def test____receive_data____connection_reset(
        self,
        protocol: StreamReaderBufferedProtocol,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()
        event_loop.call_soon(self.write_in_protocol_buffer, protocol, b"abc")
        event_loop.call_soon(protocol.connection_lost, None)

        # Act & Assert
        for _ in range(3):
            with pytest.raises(ConnectionResetError):
                _ = await data_receiver(protocol, 1024)

    @pytest.mark.asyncio
    async def test____receive_data____invalid_bufsize(
        self,
        protocol: StreamReaderBufferedProtocol,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'bufsize' must be a positive or null integer$"):
            _ = await protocol.receive_data(-1)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("read_event", ["buffer_updated", "eof_received", "connection_lost", "connection_lost_with_error"])
    async def test____receive_data____read_event_and_waiter_is_cancelled(
        self,
        read_event: Literal["buffer_updated", "eof_received", "connection_lost", "connection_lost_with_error"],
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        read_task = asyncio.create_task(data_receiver(protocol, 1024))
        await asyncio.sleep(0)
        read_task.cancel()

        # Act
        match read_event:
            case "buffer_updated":
                self.write_in_protocol_buffer(protocol, b"data")
            case "eof_received":
                self.write_eof_in_protocol_buffer(protocol)
            case "connection_lost":
                protocol.connection_lost(None)
            case "connection_lost_with_error":
                protocol.connection_lost(OSError("Something bad happen"))
            case _:
                pytest.fail("Invalid argument")
        await asyncio.wait({read_task})

        # Assert
        assert read_task.cancelled()
        mock_asyncio_transport.resume_reading.assert_not_called()

    @pytest.mark.asyncio
    async def test____receive_data____read_flow_control(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        low_water, high_water = protocol._get_read_buffer_limits()

        # Act & Assert
        while protocol._get_read_buffer_size() < high_water:
            assert not protocol._reading_paused()
            mock_asyncio_transport.pause_reading.assert_not_called()
            self.write_in_protocol_buffer(protocol, b"X")

        mock_asyncio_transport.pause_reading.assert_called_once()
        assert protocol._reading_paused()
        mock_asyncio_transport.resume_reading.assert_not_called()

        while protocol._get_read_buffer_size() > low_water:
            assert protocol._reading_paused()
            mock_asyncio_transport.resume_reading.assert_not_called()
            data = await data_receiver(protocol, 1)
            assert data == b"X"

        assert not protocol._reading_paused()
        mock_asyncio_transport.resume_reading.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception", [None, OSError("Something bad happen")])
    async def test____receive_data____buffer_release(
        self,
        exception: OSError | None,
        protocol: StreamReaderBufferedProtocol,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        self.write_in_protocol_buffer(protocol, b"abcdef")

        # Act & Assert
        protocol.connection_lost(exception)
        assert protocol._get_read_buffer_size() == 0
        with pytest.raises(BufferError):
            protocol.get_buffer(-1)

        with pytest.raises(OSError):
            _ = await data_receiver(protocol, 3)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("actual_reader", ["receive_data", "receive_data_into"])
    @pytest.mark.parametrize("new_reader", ["receive_data", "receive_data_into"])
    async def test____receive_data____concurrent_read_error(
        self,
        actual_reader: Literal["receive_data", "receive_data_into"],
        new_reader: Literal["receive_data", "receive_data_into"],
        protocol: StreamReaderBufferedProtocol,
        request: pytest.FixtureRequest,
    ) -> None:
        # Arrange
        read_task: asyncio.Task[Any]
        match actual_reader:
            case "receive_data":
                read_task = asyncio.create_task(protocol.receive_data(1024))
            case "receive_data_into":
                read_task = asyncio.create_task(protocol.receive_data_into(bytearray(1024)))
            case _:
                pytest.fail("Invalid param")
        await asyncio.sleep(0)
        request.addfinalizer(read_task.cancel)

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^\w+\(\) called while another coroutine is already waiting for incoming data$"):
            match new_reader:
                case "receive_data":
                    await protocol.receive_data(1024)
                case "receive_data_into":
                    await protocol.receive_data_into(bytearray(1024))
                case _:
                    pytest.fail("Invalid param")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____drain_helper____quick_exit_if_not_paused(
        self,
        transport_is_closing: bool,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        event_loop = asyncio.get_running_loop()
        assert not protocol._writing_paused()
        mock_create_future: MagicMock = mocker.patch.object(event_loop, "create_future")
        mock_asyncio_transport.is_closing.side_effect = [transport_is_closing]

        # Act
        await protocol.writer_drain()

        # Assert
        mock_create_future.assert_not_called()

    @pytest.mark.asyncio
    async def test____drain_helper____raise_connection_reset_if_connection_is_lost(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        assert not protocol._writing_paused()

        from errno import ECONNRESET

        protocol.connection_lost(None)
        mock_asyncio_transport.is_closing.return_value = True

        # Act & Assert
        with pytest.raises(OSError) as exc_info:
            await protocol.writer_drain()

        assert exc_info.value.errno == ECONNRESET

    @pytest.mark.asyncio
    async def test____drain_helper____connection_lost_by_unrelated_error(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
    ) -> None:
        # Arrange
        exception = OSError("Something bad happen")
        protocol.connection_lost(exception)
        mock_asyncio_transport.is_closing.return_value = True

        # Act & Assert
        with pytest.raises(OSError) as exc_info:
            await protocol.writer_drain()

        assert exc_info.value is exception

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cancel_tasks", [False, True], ids=lambda p: f"cancel_tasks_before=={p}")
    async def test____drain_helper____wait_during_writing_pause(
        self,
        cancel_tasks: bool,
        protocol: StreamReaderBufferedProtocol,
    ) -> None:
        # Arrange
        import inspect

        # Act
        protocol.pause_writing()
        assert protocol._writing_paused()
        tasks: set[asyncio.Task[None]] = set()
        for _ in range(10):
            tasks.add(asyncio.create_task(protocol.writer_drain()))
        await asyncio.sleep(0)  # Suspend to let the event loop start all tasks
        assert all(inspect.getcoroutinestate(t.get_coro()) == "CORO_SUSPENDED" for t in tasks)  # type: ignore[arg-type]
        if cancel_tasks:
            for t in tasks:
                t.cancel()
        protocol.resume_writing()
        await asyncio.sleep(0)  # Suspend to let the event loop run all tasks

        # Assert
        if cancel_tasks:
            assert all(t.done() and t.cancelled() for t in tasks)
        else:
            assert all(t.done() and t.exception() is None and t.result() is None for t in tasks)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception", [None, OSError("Something bad happen")])
    @pytest.mark.parametrize("cancel_tasks", [False, True], ids=lambda p: f"cancel_tasks_before=={p}")
    async def test____drain_helper____wait_during_writing_pause____connection_lost_while_waiting(
        self,
        cancel_tasks: bool,
        exception: Exception | None,
        protocol: StreamReaderBufferedProtocol,
    ) -> None:
        # Arrange
        import inspect

        protocol.pause_writing()
        assert protocol._writing_paused()
        tasks: set[asyncio.Task[None]] = set()
        for _ in range(10):
            tasks.add(asyncio.create_task(protocol.writer_drain()))
        await asyncio.sleep(0)  # Suspend to let the event loop start all tasks
        assert all(inspect.getcoroutinestate(t.get_coro()) == "CORO_SUSPENDED" for t in tasks)  # type: ignore[arg-type]
        if cancel_tasks:
            for t in tasks:
                t.cancel()

        # Act
        protocol.connection_lost(exception)
        await asyncio.sleep(0)  # Suspend to let the event loop run all tasks

        # Assert
        if cancel_tasks:
            assert all(t.done() and t.cancelled() for t in tasks)
        elif exception is None:
            assert all(t.done() and isinstance(t.exception(), ConnectionResetError) for t in tasks), tasks
        else:
            assert all(t.done() and t.exception() is exception for t in tasks)

    @pytest.mark.asyncio
    async def test____special_case____transport_pause_reading_not_supported(
        self,
        protocol: StreamReaderBufferedProtocol,
        mock_asyncio_transport: MagicMock,
        data_receiver: _ProtocolDataReceiver,
    ) -> None:
        # Arrange
        mock_asyncio_transport.pause_reading.side_effect = NotImplementedError
        _, high_water = protocol._get_read_buffer_limits()

        # Act & Assert
        self.write_in_protocol_buffer(protocol, b"X" * (high_water + 1))
        mock_asyncio_transport.pause_reading.assert_called_once()
        assert not protocol._reading_paused()
        mock_asyncio_transport.resume_reading.assert_not_called()

        await data_receiver(protocol, protocol._get_read_buffer_size())
        assert protocol._get_read_buffer_size() == 0

        with pytest.raises(ConnectionAbortedError):
            _ = await data_receiver(protocol, 1024)

        assert not protocol._reading_paused()
        mock_asyncio_transport.resume_reading.assert_not_called()
