# mypy: disable_error_code=override

from __future__ import annotations

import contextlib
import dataclasses
import errno
import logging
import math
import threading
from collections.abc import Callable, Generator, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel._stream import StreamDataProducer
from easynetwork.lowlevel._utils import Flag as _EasyNetworkFlag
from easynetwork.lowlevel.api_sync.servers.selector_stream import ConnectedStreamClient, SelectorStreamServer
from easynetwork.lowlevel.api_sync.transports.base_selector import (
    SelectorListener,
    SelectorStreamTransport,
    SelectorStreamWriteTransport,
    WouldBlockOnRead,
)
from easynetwork.lowlevel.request_handler import RecvAncillaryDataParams, RecvParams

import pytest

from ...._utils import (
    make_recv_noblock_into_side_effect,
    make_recv_noblock_with_ancillary_into_side_effect,
    stub_decorator,
)
from ....base import BaseTestWithStreamProtocol
from ...mock_tools import FakeSelector, make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestConnectedStreamClient(BaseTestWithStreamProtocol):
    @pytest.fixture
    @staticmethod
    def mock_stream_transport(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=SelectorStreamWriteTransport)

    @pytest.fixture
    @staticmethod
    def stream_protocol_mode() -> str:
        return "data"

    @pytest.fixture
    @staticmethod
    def reader_condvar() -> threading.Condition:
        return threading.Condition()

    @pytest.fixture
    @staticmethod
    def reader_done() -> _EasyNetworkFlag:
        return _EasyNetworkFlag(default_value=True)

    @pytest.fixture
    @staticmethod
    def client(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_wakeup_socketpair: MagicMock,
        reader_condvar: threading.Condition,
        reader_done: _EasyNetworkFlag,
    ) -> ConnectedStreamClient[Any]:
        return ConnectedStreamClient(
            _transport=mock_stream_transport,
            _transport_close_lock=threading.Lock(),
            _producer=StreamDataProducer(mock_stream_protocol),
            _wakeup_socketpair=mock_wakeup_socketpair,
            _reader_condvar=reader_condvar,
            _reader_done=reader_done,
        )

    @pytest.mark.parametrize("transport_closed", [False, True])
    def test____is_closed____default(
        self,
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
        transport_closed: bool,
    ) -> None:
        # Arrange
        mock_stream_transport.is_closed.assert_not_called()
        mock_stream_transport.is_closed.return_value = transport_closed

        # Act
        state = client.is_closed()

        # Assert
        mock_stream_transport.is_closed.assert_called_once_with()
        assert state is transport_closed

    @pytest.mark.parametrize("transport_closed", [False, True])
    def test____is_closing____default(
        self,
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
        transport_closed: bool,
    ) -> None:
        # Arrange
        if transport_closed:
            client.close()

        # Act
        state = client.is_closing()

        # Assert
        mock_stream_transport.is_closed.assert_not_called()
        assert state is transport_closed

    def test____abort____default(
        self,
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
        mock_wakeup_socketpair: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.close.assert_not_called()

        # Act
        client.abort()

        # Assert
        assert mock_stream_transport.mock_calls == [mocker.call.abort()]
        assert mock_wakeup_socketpair.mock_calls == []

    def test____abort____reader_not_done_yet(
        self,
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
        mock_wakeup_socketpair: MagicMock,
        reader_done: _EasyNetworkFlag,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.close.assert_not_called()
        reader_done.clear()
        mock_wakeup_socketpair.wakeup_thread_and_signal_safe.side_effect = reader_done.set

        # Act
        client.abort()

        # Assert
        assert mock_stream_transport.mock_calls == [mocker.call.abort()]
        assert mock_wakeup_socketpair.mock_calls == [mocker.call.wakeup_thread_and_signal_safe()]

    def test____close____default(
        self,
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
        mock_wakeup_socketpair: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.close.assert_not_called()

        # Act
        client.close()

        # Assert
        assert mock_stream_transport.mock_calls == [mocker.call.close()]
        assert mock_wakeup_socketpair.mock_calls == []

    def test____close____reader_not_done_yet(
        self,
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
        mock_wakeup_socketpair: MagicMock,
        reader_done: _EasyNetworkFlag,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.close.assert_not_called()
        reader_done.clear()
        mock_wakeup_socketpair.wakeup_thread_and_signal_safe.side_effect = reader_done.set

        # Act
        client.close()

        # Assert
        assert mock_stream_transport.mock_calls == [mocker.call.close()]
        assert mock_wakeup_socketpair.mock_calls == [mocker.call.wakeup_thread_and_signal_safe()]

    def test____extra_attributes____default(
        self,
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = client.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    @pytest.mark.parametrize("timeout", [None, 123.45], ids=lambda p: f"timeout__{p}")
    def test____send_packet____send_bytes_to_transport(
        self,
        timeout: float | None,
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_from_iterable.side_effect = lambda it, *args: chunks.extend(it)
        expected_timeout = math.inf if timeout is None else timeout

        # Act
        client.send_packet(mocker.sentinel.packet, timeout=timeout)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_from_iterable.assert_called_once_with(mocker.ANY, expected_timeout)
        assert chunks == [b"packet\n"]

    @pytest.mark.parametrize("timeout", [None, 123.45], ids=lambda p: f"timeout__{p}")
    def test____send_packet_with_ancillary____send_bytes_to_transport(
        self,
        timeout: float | None,
        client: ConnectedStreamClient[Any],
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        chunks: list[bytes] = []
        mock_stream_transport.send_all_with_ancillary.side_effect = lambda it, *args: chunks.extend(it)
        expected_timeout = math.inf if timeout is None else timeout

        # Act
        client.send_packet_with_ancillary(mocker.sentinel.packet, mocker.sentinel.ancdata, timeout=timeout)

        # Assert
        mock_stream_protocol.generate_chunks.assert_called_once_with(mocker.sentinel.packet)
        mock_stream_transport.send_all_with_ancillary.assert_called_once_with(
            mocker.ANY, mocker.sentinel.ancdata, expected_timeout
        )
        assert chunks == [b"packet\n"]


@dataclasses.dataclass
class _ServerStopHandle:
    thread: threading.Thread
    server: SelectorStreamServer[Any, Any]

    def stop(self) -> None:
        self.server.shutdown(timeout=30)
        self.thread.join(timeout=5)


type _WorkerStrategy = Literal["clients", "requests"]


def _ready_future[T](result: T) -> Future[T]:
    f: Future[T] = Future()
    f.set_result(result)
    return f


def _selector_accept_side_effect(transports: Iterable[SelectorStreamTransport]) -> Callable[..., Future[Any]]:
    transports = iter(transports)

    def side_effect(handler: Callable[..., Any], executor: ThreadPoolExecutor) -> Future[Any]:
        try:
            t = next(transports)
        except StopIteration:
            raise WouldBlockOnRead
        else:
            return executor.submit(handler, t)

    return side_effect


class TestSelectorStreamServer(BaseTestWithStreamProtocol):
    @pytest.fixture
    @staticmethod
    def mock_listener(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=SelectorListener)

    @pytest.fixture
    @staticmethod
    def mock_stream_transport(mocker: MockerFixture) -> MagicMock:
        mock_stream_transport = make_transport_mock(mocker=mocker, spec=SelectorStreamTransport)
        mock_stream_transport.recv.side_effect = NotImplementedError
        mock_stream_transport.recv_into.side_effect = NotImplementedError
        mock_stream_transport.recv_with_ancillary.side_effect = NotImplementedError
        mock_stream_transport.recv_with_ancillary_into.side_effect = NotImplementedError
        mock_stream_transport.send.side_effect = NotImplementedError
        return mock_stream_transport

    @pytest.fixture
    @staticmethod
    def max_recv_size(request: pytest.FixtureRequest) -> int:
        return getattr(request, "param", 256 * 1024)

    @pytest.fixture(params=["clients", "requests"])
    @staticmethod
    def worker_strategy(request: pytest.FixtureRequest) -> _WorkerStrategy:
        assert request.param in ("clients", "requests")
        return request.param

    @pytest.fixture
    @staticmethod
    def server(
        mock_listener: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        dummy_lock_cls: tuple[Any, Any],
        mocker: MockerFixture,
    ) -> Generator[SelectorStreamServer[Any, Any]]:
        server: SelectorStreamServer[Any, Any] = SelectorStreamServer(
            mock_listener,
            mock_stream_protocol,
            max_recv_size,
            selector_factory=FakeSelector,
        )

        with contextlib.closing(server):
            mocker.stop(dummy_lock_cls[0])
            mocker.stop(dummy_lock_cls[1])
            yield server
            server.shutdown(timeout=30)

    @classmethod
    def _start_server(
        cls,
        request: pytest.FixtureRequest,
        server: SelectorStreamServer[Any, Any],
        server_start_cb: Callable[[SelectorStreamServer[Any, Any]], None],
    ) -> _ServerStopHandle:
        thread = threading.Thread(target=server_start_cb, args=(server,), daemon=True)
        handle = _ServerStopHandle(thread, server)
        request.addfinalizer(handle.stop)
        thread.start()
        return handle

    def test____dunder_init____invalid_transport(
        self,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_listener = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a SelectorListener object, got .*$"):
            _ = SelectorStreamServer(mock_invalid_listener, mock_stream_protocol, max_recv_size)

    def test____dunder_init____invalid_protocol(
        self,
        mock_listener: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol or a BufferedStreamProtocol object, got .*$"):
            _ = SelectorStreamServer(mock_listener, mock_invalid_protocol, max_recv_size)

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size__{p}", indirect=True)
    def test____dunder_init____max_recv_size____invalid_value(
        self,
        mock_listener: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            _ = SelectorStreamServer(mock_listener, mock_stream_protocol, max_recv_size)

    def test____dunder_del____ResourceWarning(
        self,
        mock_listener: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange
        server: SelectorStreamServer[Any, Any] = SelectorStreamServer(mock_listener, mock_stream_protocol, max_recv_size)

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed server .+$",
        ):
            del server

        mock_listener.close.assert_called_once_with()

    def test____close____default(self, server: SelectorStreamServer[Any, Any], mock_listener: MagicMock) -> None:
        # Arrange
        mock_listener.close.assert_not_called()
        assert not server.is_closed()

        # Act
        server.close()

        # Assert
        mock_listener.close.assert_called_once_with()
        assert server.is_closed()

    def test____extra_attributes____default(
        self,
        server: SelectorStreamServer[Any, Any],
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_listener.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = server.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    @pytest.mark.parametrize("worker_strategy", ["unknown"])
    def test____serve____invalid_worker_strategy(
        self,
        worker_strategy: Any,
        server: SelectorStreamServer[Any, Any],
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_listener.accept_noblock.side_effect = WouldBlockOnRead
        client_connected_cb = mocker.stub()

        # Act & Assert
        with pytest.raises(AssertionError):
            with ThreadPoolExecutor(max_workers=1) as executor:
                server.serve(client_connected_cb, executor, worker_strategy=worker_strategy)
        mock_listener.accept_noblock.assert_not_called()

    def test____serve____server_closed(
        self,
        worker_strategy: Any,
        server: SelectorStreamServer[Any, Any],
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_listener.accept_noblock.side_effect = WouldBlockOnRead
        client_connected_cb = mocker.stub()
        server.close()

        # Act & Assert
        with pytest.raises(OSError, check=lambda exc: exc.errno == errno.EBADF, match=r".+ \(Server is closed\)$"):
            with ThreadPoolExecutor(max_workers=1) as executor:
                server.serve(client_connected_cb, executor, worker_strategy=worker_strategy)
        mock_listener.accept_noblock.assert_not_called()

    @pytest.mark.parametrize("give_filter", [False, True], ids=lambda p: f"give_filter__{p}")
    @pytest.mark.parametrize("recv_with_ancillary", [False, True], ids=lambda p: f"recv_with_ancillary__{p}")
    def test____serve____disconnect_error_filter____mask_connection_error_on_receive(
        self,
        request: pytest.FixtureRequest,
        give_filter: bool,
        recv_with_ancillary: bool,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_listener.accept_noblock.side_effect = _selector_accept_side_effect([mock_stream_transport])
        mock_stream_transport.recv_noblock.side_effect = ConnectionResetError
        mock_stream_transport.recv_noblock_into.side_effect = ConnectionResetError
        mock_stream_transport.recv_noblock_with_ancillary.side_effect = ConnectionResetError
        mock_stream_transport.recv_noblock_with_ancillary_into.side_effect = ConnectionResetError

        exception_caught = mocker.stub()
        request_done = threading.Event()

        @stub_decorator(mocker)
        def client_connected_cb(_: Any) -> Generator[RecvParams | None, Any]:
            try:
                if recv_with_ancillary:
                    ancillary_data_received = mocker.stub("ancillary_data_received")
                    yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))
                else:
                    yield None
            except ConnectionResetError:
                exception_caught(False)
            except GeneratorExit:
                exception_caught(True)
                raise
            else:
                exception_caught(None)
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            if give_filter:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve(
                        client_connected_cb,
                        executor,
                        worker_strategy=worker_strategy,
                        disconnect_error_filter=lambda exc: isinstance(exc, ConnectionError),
                        ancillary_bufsize=(1024 if recv_with_ancillary else None),
                    ),
                )
            else:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve(
                        client_connected_cb,
                        executor,
                        worker_strategy=worker_strategy,
                        ancillary_bufsize=(1024 if recv_with_ancillary else None),
                    ),
                )
            request_done.wait(2)
            handle.stop()

        client_connected_cb.assert_called_once()
        exception_caught.assert_called_once_with(True if give_filter else False)

    @pytest.mark.parametrize("recv_with_ancillary", [False, True], ids=lambda p: f"recv_with_ancillary__{p}")
    def test____serve____disconnect_error_filter____reraise_non_filtered_errors(
        self,
        request: pytest.FixtureRequest,
        recv_with_ancillary: bool,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_listener.accept_noblock.side_effect = _selector_accept_side_effect([mock_stream_transport])
        mock_stream_transport.recv_noblock.side_effect = OSError
        mock_stream_transport.recv_noblock_into.side_effect = OSError
        mock_stream_transport.recv_noblock_with_ancillary.side_effect = OSError
        mock_stream_transport.recv_noblock_with_ancillary_into.side_effect = OSError

        exception_caught = mocker.stub()
        request_done = threading.Event()

        @stub_decorator(mocker)
        def client_connected_cb(_: Any) -> Generator[RecvParams | None, Any]:
            try:
                if recv_with_ancillary:
                    ancillary_data_received = mocker.stub("ancillary_data_received")
                    yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))
                else:
                    yield None
            except OSError:
                exception_caught(False)
            except GeneratorExit:
                exception_caught(True)
                raise
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve(
                    client_connected_cb,
                    executor,
                    worker_strategy=worker_strategy,
                    disconnect_error_filter=lambda exc: isinstance(exc, ConnectionError),
                    ancillary_bufsize=(1024 if recv_with_ancillary else None),
                ),
            )
            request_done.wait(2)
            handle.stop()

        client_connected_cb.assert_called_once()
        exception_caught.assert_called_once_with(False)

    def test____serve____timeout____old_method_is_forbidden(
        self,
        request: pytest.FixtureRequest,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.WARNING)

        mock_listener.accept_noblock.side_effect = _selector_accept_side_effect([mock_stream_transport])
        mock_stream_transport.recv_noblock.side_effect = [b"packet\n"]
        mock_stream_transport.recv_noblock_into.side_effect = make_recv_noblock_into_side_effect([b"packet\n"])

        request_done = threading.Event()

        @stub_decorator(mocker)
        def client_connected_cb(_: Any) -> Generator[float, Any]:
            try:
                with pytest.raises(TypeError, match=r"^Expected a 'RecvParams' object, got 1234.0 instead\.$"):
                    yield 1234.0
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve(
                    client_connected_cb,
                    executor,
                    worker_strategy=worker_strategy,
                    disconnect_error_filter=lambda exc: isinstance(exc, ConnectionError),
                ),
            )
            request_done.wait(2)
            handle.stop()

        client_connected_cb.assert_called_once()
        assert not caplog.records

    @pytest.mark.parametrize("invalid_timeout", [-1.0, math.nan])
    @pytest.mark.parametrize("recv_with_ancillary", [False, True], ids=lambda p: f"recv_with_ancillary__{p}")
    def test____serve____invalid_timeout(
        self,
        request: pytest.FixtureRequest,
        invalid_timeout: float,
        recv_with_ancillary: bool,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        mock_listener.accept_noblock.side_effect = _selector_accept_side_effect([mock_stream_transport])
        mock_stream_transport.recv_noblock.side_effect = OSError
        mock_stream_transport.recv_noblock_into.side_effect = OSError
        mock_stream_transport.recv_noblock_with_ancillary.side_effect = OSError
        mock_stream_transport.recv_noblock_with_ancillary_into.side_effect = OSError

        request_done = threading.Event()

        @stub_decorator(mocker)
        def client_connected_cb(_: Any) -> Generator[RecvParams, Any]:
            try:
                with pytest.raises(ValueError, match=r"^Invalid delay: .+$"):
                    if recv_with_ancillary:
                        ancillary_data_received = mocker.stub("ancillary_data_received")
                        yield RecvParams(
                            timeout=invalid_timeout,
                            recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received),
                        )
                    else:
                        yield RecvParams(timeout=invalid_timeout)
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve(
                    client_connected_cb,
                    executor,
                    worker_strategy=worker_strategy,
                    ancillary_bufsize=(1024 if recv_with_ancillary else None),
                ),
            )
            request_done.wait(2)
            handle.stop()

        client_connected_cb.assert_called_once()
        assert not caplog.records

    @pytest.mark.parametrize("recv_with_ancillary", [False, True], ids=lambda p: f"recv_with_ancillary__{p}")
    def test____serve____unhandled_exception____from_system(
        self,
        request: pytest.FixtureRequest,
        recv_with_ancillary: bool,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        mock_listener.accept_noblock.side_effect = _selector_accept_side_effect([mock_stream_transport])
        mock_stream_transport.recv_noblock.side_effect = OSError("recv() error")
        mock_stream_transport.recv_noblock_into.side_effect = OSError("recv() error")
        mock_stream_transport.recv_noblock_with_ancillary.side_effect = OSError("recv() error")
        mock_stream_transport.recv_noblock_with_ancillary_into.side_effect = OSError("recv() error")

        request_done = threading.Event()

        @stub_decorator(mocker)
        def client_connected_cb(_: Any) -> Generator[RecvParams | None, Any]:
            try:
                if recv_with_ancillary:
                    ancillary_data_received = mocker.stub("ancillary_data_received")
                    yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))
                else:
                    yield None
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve(
                    client_connected_cb,
                    executor,
                    worker_strategy=worker_strategy,
                    ancillary_bufsize=(1024 if recv_with_ancillary else None),
                ),
            )
            request_done.wait(2)
            handle.stop()

        client_connected_cb.assert_called_once()
        assert len(caplog.records) == 1 and caplog.records[0].exc_info is not None
        assert isinstance(caplog.records[0].exc_info[1], OSError)
        assert caplog.records[0].getMessage() == "Unhandled exception: recv() error"

    @pytest.mark.parametrize("recv_with_ancillary", [False, True], ids=lambda p: f"recv_with_ancillary__{p}")
    def test____serve____unhandled_exception____from_request_handler(
        self,
        request: pytest.FixtureRequest,
        recv_with_ancillary: bool,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        mock_listener.accept_noblock.side_effect = _selector_accept_side_effect([mock_stream_transport])
        mock_stream_transport.recv_noblock.side_effect = [b"packet\n"]
        mock_stream_transport.recv_noblock_into.side_effect = make_recv_noblock_into_side_effect([b"packet\n"])
        mock_stream_transport.recv_noblock_with_ancillary.side_effect = [(b"packet\n", mocker.sentinel.ancdata)]
        mock_stream_transport.recv_noblock_with_ancillary_into.side_effect = make_recv_noblock_with_ancillary_into_side_effect(
            [(b"packet\n", mocker.sentinel.ancdata)]
        )

        request_done = threading.Event()

        @stub_decorator(mocker)
        def client_connected_cb(_: Any) -> Generator[RecvParams | None, Any]:
            try:
                if recv_with_ancillary:
                    ancillary_data_received = mocker.stub("ancillary_data_received")
                    yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))
                    ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)
                else:
                    yield None
                raise ValueError("something bad happened")
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve(
                    client_connected_cb,
                    executor,
                    worker_strategy=worker_strategy,
                    ancillary_bufsize=(1024 if recv_with_ancillary else None),
                ),
            )
            request_done.wait(2)
            handle.stop()

        client_connected_cb.assert_called_once()
        assert len(caplog.records) == 1 and caplog.records[0].exc_info is not None
        assert isinstance(caplog.records[0].exc_info[1], ValueError)
        assert caplog.records[0].getMessage() == "Unhandled exception: something bad happened"

    @pytest.mark.parametrize("ancillary_bufsize", [0, -42, 3.14])
    def test____serve____recv_with_ancillary____invalid_bufsize(
        self,
        ancillary_bufsize: Any,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_listener.accept_noblock.side_effect = WouldBlockOnRead
        client_connected_cb = mocker.stub()

        # Act & Assert
        with pytest.raises(ValueError, match=r"^ancillary_bufsize must be a strictly positive integer$"):
            with ThreadPoolExecutor(max_workers=1) as executor:
                server.serve(client_connected_cb, executor, worker_strategy=worker_strategy, ancillary_bufsize=ancillary_bufsize)
        mock_listener.accept_noblock.assert_not_called()

    def test____serve____recv_with_ancillary____unsupported_by_default(
        self,
        request: pytest.FixtureRequest,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        mock_listener.accept_noblock.side_effect = _selector_accept_side_effect([mock_stream_transport])
        mock_stream_transport.recv_noblock.side_effect = OSError
        mock_stream_transport.recv_noblock_into.side_effect = OSError
        mock_stream_transport.recv_noblock_with_ancillary.side_effect = [(b"packet\n", mocker.sentinel.ancdata)]
        mock_stream_transport.recv_noblock_with_ancillary_into.side_effect = make_recv_noblock_with_ancillary_into_side_effect(
            [(b"packet\n", mocker.sentinel.ancdata)]
        )

        request_done = threading.Event()

        @stub_decorator(mocker)
        def client_connected_cb(_: Any) -> Generator[RecvParams, Any]:
            ancillary_data_received = mocker.stub("ancillary_data_received")
            try:
                with pytest.raises(
                    UnsupportedOperation,
                    match=r"^The server is not configured to handle ancillary data \(ancillary_bufsize=None\)\.$",
                ):
                    yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))

                ancillary_data_received.assert_not_called()
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve(
                    client_connected_cb,
                    executor,
                    worker_strategy=worker_strategy,
                ),
            )
            request_done.wait(2)
            handle.stop()

        client_connected_cb.assert_called_once()
        mock_stream_transport.recv_noblock_with_ancillary.assert_not_called()
        mock_stream_transport.recv_noblock_with_ancillary_into.assert_not_called()
        assert not caplog.records

    def test____serve____recv_with_ancillary____ancillary_data_received_callback_crashed(
        self,
        request: pytest.FixtureRequest,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        mock_listener.accept_noblock.side_effect = _selector_accept_side_effect([mock_stream_transport])
        mock_stream_transport.recv_noblock.side_effect = OSError
        mock_stream_transport.recv_noblock_into.side_effect = OSError
        mock_stream_transport.recv_noblock_with_ancillary.side_effect = [(b"packet\n", mocker.sentinel.ancdata)]
        mock_stream_transport.recv_noblock_with_ancillary_into.side_effect = make_recv_noblock_with_ancillary_into_side_effect(
            [(b"packet\n", mocker.sentinel.ancdata)]
        )

        request_done = threading.Event()

        @stub_decorator(mocker)
        def client_connected_cb(_: Any) -> Generator[RecvParams, Any]:
            ancillary_data_received = mocker.stub("ancillary_data_received")
            ancillary_data_received.side_effect = expected_error = Exception("Error")
            try:
                with pytest.raises(RuntimeError, match=r"^RecvAncillaryDataParams\.data_received\(\) crashed$") as exc_info:
                    yield RecvParams(
                        recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received),
                    )

                assert exc_info.value.__cause__ is expected_error
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve(
                    client_connected_cb,
                    executor,
                    worker_strategy=worker_strategy,
                    ancillary_bufsize=1024,
                ),
            )
            request_done.wait(2)
            handle.stop()

        client_connected_cb.assert_called_once()
        assert not caplog.records

    def test____serve____recv_with_ancillary____partial_data(
        self,
        request: pytest.FixtureRequest,
        worker_strategy: _WorkerStrategy,
        server: SelectorStreamServer[Any, Any],
        mock_stream_transport: MagicMock,
        mock_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        caplog.set_level(logging.ERROR)

        mock_listener.accept_noblock.side_effect = _selector_accept_side_effect([mock_stream_transport])
        mock_stream_transport.recv_noblock.side_effect = OSError
        mock_stream_transport.recv_noblock_into.side_effect = OSError
        mock_stream_transport.recv_noblock_with_ancillary.side_effect = [(b"pac", mocker.sentinel.ancdata), (b"ket\n", None)]
        mock_stream_transport.recv_noblock_with_ancillary_into.side_effect = make_recv_noblock_with_ancillary_into_side_effect(
            [(b"pac", mocker.sentinel.ancdata), (b"ket\n", None)]
        )

        request_done = threading.Event()

        @stub_decorator(mocker)
        def client_connected_cb(_: Any) -> Generator[RecvParams | float, Any]:
            ancillary_data_received = mocker.stub("ancillary_data_received")

            try:
                with pytest.raises(EOFError, match=r"^Received partial packet data$"):
                    yield RecvParams(
                        recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received),
                    )

                ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve(
                    client_connected_cb,
                    executor,
                    worker_strategy=worker_strategy,
                    ancillary_bufsize=1024,
                ),
            )
            request_done.wait(2)
            handle.stop()

        client_connected_cb.assert_called_once()
        assert not caplog.records
