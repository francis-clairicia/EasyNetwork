from __future__ import annotations

import contextlib
import dataclasses
import errno
import logging
import math
import threading
from collections.abc import Callable, Generator, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, overload

from easynetwork.exceptions import DatagramProtocolParseError, UnsupportedOperation
from easynetwork.lowlevel.api_sync.servers.selector_datagram import SelectorDatagramServer, _ClientData, _ClientState
from easynetwork.lowlevel.api_sync.transports.base_selector import SelectorDatagramListener, WouldBlockOnRead
from easynetwork.lowlevel.request_handler import RecvAncillaryDataParams, RecvParams

import pytest

from ...._utils import stub_decorator
from ....base import BaseTestWithDatagramProtocol
from ...mock_tools import FakeSelector, make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@dataclasses.dataclass
class _ServerStopHandle:
    thread: threading.Thread
    server: SelectorDatagramServer[Any, Any, Any]

    def stop(self) -> None:
        self.server.shutdown(timeout=30)
        self.thread.join(timeout=5)


@overload
def _selector_recv_side_effect(packets: Iterable[tuple[bytes, Any]]) -> Callable[..., tuple[bytes, Any]]: ...


@overload
def _selector_recv_side_effect(packets: Iterable[tuple[bytes, Any, Any]]) -> Callable[..., tuple[bytes, Any, Any]]: ...


def _selector_recv_side_effect(
    packets: Iterable[tuple[bytes, Any] | tuple[bytes, Any, Any]],
) -> Callable[..., tuple[bytes, Any] | tuple[bytes, Any, Any]]:
    packets = iter(packets)

    def side_effect(*args: Any, **kwargs: Any) -> tuple[bytes, Any] | tuple[bytes, Any, Any]:
        try:
            t = next(packets)
        except StopIteration:
            raise WouldBlockOnRead
        else:
            return t

    return side_effect


def _set_selector_recv_side_effect(
    mock_datagram_listener: MagicMock,
    packets: Iterable[tuple[bytes, Any, Any]],
) -> None:
    mock_datagram_listener.recv_noblock_from.side_effect = _selector_recv_side_effect([(p[0], p[2]) for p in packets])
    mock_datagram_listener.recv_noblock_with_ancillary_from.side_effect = _selector_recv_side_effect(packets)


class TestSelectorDatagramServer(BaseTestWithDatagramProtocol):
    @pytest.fixture
    @staticmethod
    def mock_datagram_listener(mocker: MockerFixture) -> MagicMock:
        mock_datagram_listener = make_transport_mock(mocker=mocker, spec=SelectorDatagramListener)
        mock_datagram_listener.recv_from.side_effect = NotImplementedError
        mock_datagram_listener.recv_with_ancillary_from.side_effect = NotImplementedError
        mock_datagram_listener.send_noblock_to.side_effect = NotImplementedError
        mock_datagram_listener.send_noblock_with_ancillary_to.side_effect = NotImplementedError
        return mock_datagram_listener

    @pytest.fixture
    @staticmethod
    def server(
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
        dummy_lock_cls: tuple[Any, Any],
        mocker: MockerFixture,
    ) -> Generator[SelectorDatagramServer[Any, Any, Any]]:
        server: SelectorDatagramServer[Any, Any, Any] = SelectorDatagramServer(
            mock_datagram_listener,
            mock_datagram_protocol,
            selector_factory=FakeSelector,
        )
        with contextlib.closing(server):
            mocker.stop(dummy_lock_cls[0])
            mocker.stop(dummy_lock_cls[1])
            yield server
            server.shutdown(timeout=5)

    @pytest.fixture
    @staticmethod
    def ancillary_data_unused(request: pytest.FixtureRequest, mocker: MockerFixture) -> MagicMock | None:
        match getattr(request, "param", True):
            case True:
                return mocker.stub("ancillary_data_unused")
            case False:
                return None
            case _:
                pytest.fail(f"Invalid parameter: {request.param}")

    @classmethod
    def _start_server(
        cls,
        request: pytest.FixtureRequest,
        server: SelectorDatagramServer[Any, Any, Any],
        server_start_cb: Callable[[SelectorDatagramServer[Any, Any, Any]], None],
    ) -> _ServerStopHandle:
        thread = threading.Thread(target=server_start_cb, args=(server,), daemon=True)
        handle = _ServerStopHandle(thread, server)
        request.addfinalizer(handle.stop)
        thread.start()
        return handle

    def test____dunder_init____invalid_transport(
        self,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_listener = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a SelectorDatagramListener object, got .*$"):
            _ = SelectorDatagramServer(mock_invalid_listener, mock_datagram_protocol)

    def test____dunder_init____invalid_protocol(
        self,
        mock_datagram_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = SelectorDatagramServer(mock_datagram_listener, mock_invalid_protocol)

    def test____dunder_del____ResourceWarning(
        self,
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        server: SelectorDatagramServer[Any, Any, Any] = SelectorDatagramServer(mock_datagram_listener, mock_datagram_protocol)

        # Act & Assert
        with pytest.warns(
            ResourceWarning,
            match=r"^unclosed server .+$",
        ):
            del server

        mock_datagram_listener.close.assert_called()

    def test____close____default(
        self,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_listener.close.assert_not_called()

        # Act
        server.close()

        # Assert
        mock_datagram_listener.close.assert_called_once_with()

    def test____serve____server_closed(
        self,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_listener.recv_noblock_from.side_effect = WouldBlockOnRead
        mock_datagram_listener.recv_noblock_with_ancillary_from.side_effect = WouldBlockOnRead
        client_connected_cb = mocker.stub()
        server.close()

        # Act & Assert
        with pytest.raises(OSError, check=lambda exc: exc.errno == errno.EBADF, match=r".+ \(Server is closed\)$"):
            with ThreadPoolExecutor(max_workers=1) as executor:
                server.serve(client_connected_cb, executor)
        mock_datagram_listener.recv_noblock_from.assert_not_called()
        mock_datagram_listener.recv_noblock_with_ancillary_from.assert_not_called()

    @pytest.mark.parametrize("after_first_yield", [False, True], ids=lambda p: f"after_first_yield__{p}")
    @pytest.mark.parametrize("recv_with_ancillary", [False, True], ids=lambda p: f"recv_with_ancillary__{p}")
    def test____serve____timeout____old_method_is_forbidden(
        self,
        request: pytest.FixtureRequest,
        after_first_yield: bool,
        recv_with_ancillary: bool,
        server: SelectorDatagramServer[Any, Any, Any],
        ancillary_data_unused: MagicMock,
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        _set_selector_recv_side_effect(mock_datagram_listener, [(b"packet", mocker.sentinel.ancdata, mocker.sentinel.address)])

        request_done = threading.Event()

        @stub_decorator(mocker)
        def datagram_received_cb(_: Any) -> Generator[float | RecvParams | None, Any]:
            ancillary_data_received = mocker.stub("ancillary_data_received")
            try:
                if after_first_yield:
                    if recv_with_ancillary:
                        packet = yield RecvParams(
                            timeout=1.0,
                            recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received),
                        )
                        ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)
                    else:
                        packet = yield RecvParams(timeout=1.0)
                    assert packet is mocker.sentinel.packet
                with pytest.raises(TypeError, match=r"^Expected a 'RecvParams' object, got 1234.0 instead\.$"):
                    yield 1234.0
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            if recv_with_ancillary:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve_with_ancillary(datagram_received_cb, executor, 1024, ancillary_data_unused),
                )
            else:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve(datagram_received_cb, executor),
                )
            if not request_done.wait(2):
                raise AssertionError("request handler not done after 2 seconds")
            handle.stop()

        datagram_received_cb.assert_called_once()
        assert not caplog.records
        if recv_with_ancillary and not after_first_yield:
            ancillary_data_unused.assert_called_once_with(mocker.sentinel.ancdata, mocker.sentinel.address)

    @pytest.mark.parametrize("invalid_timeout", [-1.0, math.nan])
    @pytest.mark.parametrize("invalid_timeout_after_first_yield", [False, True], ids=lambda p: f"after_first_yield__{p}")
    @pytest.mark.parametrize("recv_with_ancillary", [False, True], ids=lambda p: f"recv_with_ancillary__{p}")
    def test____serve____invalid_timeout(
        self,
        request: pytest.FixtureRequest,
        invalid_timeout: float,
        invalid_timeout_after_first_yield: bool,
        recv_with_ancillary: bool,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        _set_selector_recv_side_effect(mock_datagram_listener, [(b"packet", mocker.sentinel.ancdata, mocker.sentinel.address)])

        request_done = threading.Event()

        @stub_decorator(mocker)
        def datagram_received_cb(_: Any) -> Generator[RecvParams | None, Any]:
            ancillary_data_received = mocker.stub("ancillary_data_received")
            try:
                if invalid_timeout_after_first_yield:
                    if recv_with_ancillary:
                        yield RecvParams(timeout=1.0, recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))
                        ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)
                    else:
                        yield RecvParams(timeout=1.0)
                with pytest.raises(ValueError, match=r"^Invalid delay: .+$"):
                    if recv_with_ancillary:
                        yield RecvParams(
                            timeout=invalid_timeout,
                            recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received),
                        )
                    else:
                        yield RecvParams(timeout=invalid_timeout)
                if recv_with_ancillary:
                    assert ancillary_data_received.mock_calls == [
                        mocker.call(mocker.sentinel.ancdata),
                    ]
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            if recv_with_ancillary:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve_with_ancillary(datagram_received_cb, executor, 1024, None),
                )
            else:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve(datagram_received_cb, executor),
                )
            if not request_done.wait(2):
                raise AssertionError("request handler not done after 2 seconds")
            handle.stop()

        datagram_received_cb.assert_called_once()
        assert not caplog.records

    @pytest.mark.parametrize("recv_with_ancillary", [False, True], ids=lambda p: f"recv_with_ancillary__{p}")
    def test____serve____unhandled_exception____from_system(
        self,
        request: pytest.FixtureRequest,
        recv_with_ancillary: bool,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        _set_selector_recv_side_effect(
            mock_datagram_listener,
            [
                # mock_datagram_protocol does not accept non-ASCII strings.
                ("\u00e9".encode("latin-1"), mocker.sentinel.ancdata, mocker.sentinel.address),
            ],
        )

        request_done = threading.Event()

        @stub_decorator(mocker)
        def datagram_received_cb(_: Any) -> Generator[RecvParams | None, Any]:
            try:
                if recv_with_ancillary:
                    ancillary_data_received = mocker.stub("ancillary_data_received")
                    try:
                        yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))
                    finally:
                        ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)
                else:
                    yield None
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            if recv_with_ancillary:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve_with_ancillary(datagram_received_cb, executor, 1024, None),
                )
            else:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve(datagram_received_cb, executor),
                )
            if not request_done.wait(2):
                raise AssertionError("request handler not done after 2 seconds")
            handle.stop()

        datagram_received_cb.assert_called_once()
        assert len(caplog.records) == 1 and caplog.records[0].exc_info is not None
        assert isinstance(caplog.records[0].exc_info[1], DatagramProtocolParseError)
        assert caplog.records[0].getMessage().startswith("Unhandled exception:")

    @pytest.mark.parametrize("recv_with_ancillary", [False, True], ids=lambda p: f"recv_with_ancillary__{p}")
    def test____serve____unhandled_exception____from_request_handler(
        self,
        request: pytest.FixtureRequest,
        recv_with_ancillary: bool,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        _set_selector_recv_side_effect(mock_datagram_listener, [(b"packet", mocker.sentinel.ancdata, mocker.sentinel.address)])

        request_done = threading.Event()

        @stub_decorator(mocker)
        def datagram_received_cb(_: Any) -> Generator[None, Any]:
            try:
                yield
                raise ValueError("something bad happened")
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            if recv_with_ancillary:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve_with_ancillary(datagram_received_cb, executor, 1024, None),
                )
            else:
                handle = self._start_server(
                    request,
                    server,
                    lambda server: server.serve(datagram_received_cb, executor),
                )
            if not request_done.wait(2):
                raise AssertionError("request handler not done after 2 seconds")
            handle.stop()

        datagram_received_cb.assert_called_once()
        assert len(caplog.records) == 1 and caplog.records[0].exc_info is not None
        assert isinstance(caplog.records[0].exc_info[1], ValueError)
        assert caplog.records[0].getMessage() == "Unhandled exception: something bad happened"

    @pytest.mark.parametrize("after_first_yield", [False, True], ids=lambda p: f"after_first_yield__{p}")
    def test____serve____ancillary_data_asked_while_unsupported(
        self,
        request: pytest.FixtureRequest,
        after_first_yield: bool,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        mock_datagram_listener.recv_noblock_from.side_effect = _selector_recv_side_effect([(b"packet", mocker.sentinel.address)])
        mock_datagram_listener.recv_noblock_with_ancillary_from.side_effect = UnsupportedOperation

        request_done = threading.Event()

        @stub_decorator(mocker)
        def datagram_received_cb(_: Any) -> Generator[RecvParams | None, Any]:
            try:
                if after_first_yield:
                    yield RecvParams()

                ancillary_data_received = mocker.stub("ancillary_data_received")
                with pytest.raises(UnsupportedOperation, match=r"^The server is not configured to handle ancillary data\.$"):
                    yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve(datagram_received_cb, executor),
            )
            if not request_done.wait(2):
                raise AssertionError("request handler not done after 2 seconds")
            handle.stop()

        datagram_received_cb.assert_called_once()
        assert not caplog.records

    @pytest.mark.parametrize("after_first_yield", [False, True], ids=lambda p: f"after_first_yield__{p}")
    def test____serve____recv_with_ancillary____ancillary_data_received_callback_crashed(
        self,
        request: pytest.FixtureRequest,
        after_first_yield: bool,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        _set_selector_recv_side_effect(
            mock_datagram_listener,
            [(b"packet", mocker.sentinel.ancdata, mocker.sentinel.address)] * (2 if after_first_yield else 1),
        )

        request_done = threading.Event()

        @stub_decorator(mocker)
        def datagram_received_cb(_: Any) -> Generator[RecvParams | None, Any]:
            ancillary_data_received = mocker.stub("ancillary_data_received")
            try:
                if after_first_yield:
                    yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))
                    ancillary_data_received.assert_called_once_with(mocker.sentinel.ancdata)

                ancillary_data_received.side_effect = expected_error = Exception("Error")
                with pytest.raises(RuntimeError, match=r"^RecvAncillaryDataParams\.data_received\(\) crashed$") as exc_info:
                    yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))

                assert exc_info.value.__cause__ is expected_error
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve_with_ancillary(datagram_received_cb, executor, 1024, None),
            )
            if not request_done.wait(2):
                raise AssertionError("request handler not done after 2 seconds")
            handle.stop()

        datagram_received_cb.assert_called_once()
        assert not caplog.records

    @pytest.mark.parametrize(
        ["ancillary_data_unused", "ancillary_data_unused_callback_crash"],
        [
            pytest.param(False, False, id="ancillary_data_unused__False-ancillary_data_unused_callback_crash__False"),
            pytest.param(True, False, id="ancillary_data_unused__True-ancillary_data_unused_callback_crash__False"),
            pytest.param(True, True, id="ancillary_data_unused__True-ancillary_data_unused_callback_crash__True"),
        ],
        indirect=["ancillary_data_unused"],
    )
    @pytest.mark.parametrize("after_first_yield", [None, False, True], ids=lambda p: f"after_first_yield__{p}")
    def test____serve____recv_with_ancillary____ancillary_data_unused(
        self,
        request: pytest.FixtureRequest,
        after_first_yield: bool | None,
        ancillary_data_unused: MagicMock | None,
        ancillary_data_unused_callback_crash: bool,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if ancillary_data_unused_callback_crash:
            if ancillary_data_unused is None:
                pytest.skip("Useless combination.")
            ancillary_data_unused.side_effect = Exception("ancillary_data_unused side effect")

        caplog.set_level(logging.ERROR)

        packets = [(b"packet", mocker.sentinel.ancdata_1, mocker.sentinel.address)]
        if after_first_yield:
            packets.append((b"packet", mocker.sentinel.ancdata_2, mocker.sentinel.address))
        _set_selector_recv_side_effect(mock_datagram_listener, packets)

        request_done = threading.Event()

        @stub_decorator(mocker)
        def datagram_received_cb(_: Any) -> Generator[None, Any]:
            try:
                if after_first_yield is None:
                    return
                if after_first_yield:
                    yield
                yield
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve_with_ancillary(datagram_received_cb, executor, 1024, ancillary_data_unused),
            )
            if not request_done.wait(2):
                raise AssertionError("request handler not done after 2 seconds")
            handle.stop()

        datagram_received_cb.assert_called_once()
        if ancillary_data_unused_callback_crash:
            assert ancillary_data_unused is not None
            assert len(caplog.records) == (2 if after_first_yield else 1)
            for r in caplog.records:
                assert r.exc_info is not None
                assert isinstance(r.exc_info[1], RuntimeError)
                assert r.getMessage() == "Unhandled exception: ancillary_data_unused() crashed"
                assert r.exc_info[1].__cause__ is ancillary_data_unused.side_effect
        else:
            assert not caplog.records
        if ancillary_data_unused is not None:
            match after_first_yield:
                case None | False:
                    assert ancillary_data_unused.mock_calls == [mocker.call(mocker.sentinel.ancdata_1, mocker.sentinel.address)]
                case _:
                    assert ancillary_data_unused.mock_calls == [
                        mocker.call(mocker.sentinel.ancdata_1, mocker.sentinel.address),
                        mocker.call(mocker.sentinel.ancdata_2, mocker.sentinel.address),
                    ]

    @pytest.mark.parametrize("after_first_yield", [None, False, True], ids=lambda p: f"after_first_yield__{p}")
    @pytest.mark.parametrize("try_to_handle_ancillary_data", [False, True], ids=lambda p: f"try_to_handle_ancillary_data__{p}")
    def test____serve____recv_with_ancillary____no_ancillary_data(
        self,
        request: pytest.FixtureRequest,
        after_first_yield: bool | None,
        try_to_handle_ancillary_data: bool,
        ancillary_data_unused: MagicMock,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        _set_selector_recv_side_effect(
            mock_datagram_listener,
            [(b"packet", None, mocker.sentinel.address)] * (2 if after_first_yield else 1),
        )

        request_done = threading.Event()

        @stub_decorator(mocker)
        def datagram_received_cb(_: Any) -> Generator[RecvParams | None, Any]:
            try:
                if after_first_yield is None:
                    return
                ancillary_data_received = mocker.stub("ancillary_data_received")
                if after_first_yield:
                    yield None
                try:
                    if try_to_handle_ancillary_data:
                        yield RecvParams(recv_with_ancillary=RecvAncillaryDataParams(ancillary_data_received))
                    else:
                        yield None
                finally:
                    ancillary_data_received.assert_not_called()
            finally:
                request_done.set()

        # Act & Assert
        with ThreadPoolExecutor(max_workers=1) as executor:
            handle = self._start_server(
                request,
                server,
                lambda server: server.serve_with_ancillary(datagram_received_cb, executor, 1024, ancillary_data_unused),
            )
            if not request_done.wait(2):
                raise AssertionError("request handler not done after 2 seconds")
            handle.stop()

        datagram_received_cb.assert_called_once()
        assert not caplog.records
        ancillary_data_unused.assert_not_called()

    @pytest.mark.parametrize("ancillary_bufsize", [0, -42, 3.14])
    def test____serve_with_ancillary____invalid_bufsize(
        self,
        request: pytest.FixtureRequest,
        ancillary_bufsize: Any,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.ERROR)

        mock_datagram_listener.recv_noblock_from.side_effect = AssertionError
        mock_datagram_listener.recv_noblock_with_ancillary_from.side_effect = AssertionError

        @stub_decorator(mocker)
        def datagram_received_cb(_: Any) -> Generator[RecvParams | None, Any]:
            yield None

        # Act & Assert
        with pytest.raises(ValueError, match=r"^ancillary_bufsize must be a strictly positive integer$"):
            with ThreadPoolExecutor(max_workers=1) as executor:
                server.serve_with_ancillary(datagram_received_cb, executor, ancillary_bufsize=ancillary_bufsize)

        datagram_received_cb.assert_not_called()
        assert not caplog.records
        mock_datagram_listener.recv_noblock_from.assert_not_called()
        mock_datagram_listener.recv_noblock_with_ancillary_from.assert_not_called()

    def test____extra_attributes____default(
        self,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_listener.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = server.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    def test____send_packet_to____send_bytes_to_transport(
        self,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_listener.send_to.return_value = None

        # Act
        server.send_packet_to(mocker.sentinel.packet, mocker.sentinel.destination, timeout=mocker.sentinel.timeout)

        # Assert
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_datagram_listener.send_to.assert_called_once_with(b"packet", mocker.sentinel.destination, mocker.sentinel.timeout)
        mock_datagram_listener.send_with_ancillary_to.assert_not_called()

    def test____send_packet_to____protocol_crashed(
        self,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_listener.send_to.return_value = None
        expected_error = Exception("Error")
        mock_datagram_protocol.make_datagram.side_effect = expected_error

        # Act & Assert
        with pytest.raises(
            RuntimeError,
            match=r"^protocol\.make_datagram\(\) crashed$",
            check=lambda exc: exc.__cause__ is expected_error,
        ):
            server.send_packet_to(mocker.sentinel.packet, mocker.sentinel.destination)

        mock_datagram_listener.send_to.assert_not_called()
        mock_datagram_listener.send_with_ancillary_to.assert_not_called()

    def test____send_packet_with_ancillary_to____send_bytes_to_transport(
        self,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_listener.send_with_ancillary_to.return_value = None

        # Act
        server.send_packet_with_ancillary_to(
            mocker.sentinel.packet,
            mocker.sentinel.ancdata,
            mocker.sentinel.destination,
            timeout=mocker.sentinel.timeout,
        )

        # Assert
        mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
        mock_datagram_listener.send_with_ancillary_to.assert_called_once_with(
            b"packet",
            mocker.sentinel.ancdata,
            mocker.sentinel.destination,
            mocker.sentinel.timeout,
        )
        mock_datagram_listener.send_to.assert_not_called()

    def test____send_packet_with_ancillary_to____protocol_crashed(
        self,
        server: SelectorDatagramServer[Any, Any, Any],
        mock_datagram_listener: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_listener.send_with_ancillary_to.return_value = None
        expected_error = Exception("Error")
        mock_datagram_protocol.make_datagram.side_effect = expected_error

        # Act & Assert
        with pytest.raises(
            RuntimeError,
            match=r"^protocol\.make_datagram\(\) crashed$",
            check=lambda exc: exc.__cause__ is expected_error,
        ):
            server.send_packet_with_ancillary_to(mocker.sentinel.packet, mocker.sentinel.ancdata, mocker.sentinel.destination)

        # Assert
        mock_datagram_listener.send_with_ancillary_to.assert_not_called()
        mock_datagram_listener.send_to.assert_not_called()


class TestClientData:

    @pytest.fixture
    @staticmethod
    def client_data() -> _ClientData:
        return _ClientData()

    @staticmethod
    def get_client_state(client_data: _ClientData) -> _ClientState | None:
        return client_data.state

    def test____dunder_init____default(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        assert client_data.state is None

    def test____client_state____regular_state_transition(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        assert self.get_client_state(client_data) is None
        client_data.mark_pending()
        assert self.get_client_state(client_data) is _ClientState.TASK_PENDING
        client_data.mark_running()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        client_data.mark_done()
        assert self.get_client_state(client_data) is None

    def test____client_state____regular_state_transition____task_cancellation(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        assert self.get_client_state(client_data) is None
        client_data.mark_pending()
        assert self.get_client_state(client_data) is _ClientState.TASK_PENDING
        client_data.mark_done_by_cancellation()
        assert self.get_client_state(client_data) is None

    def test____client_state____irregular_state_transition(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        ## Case 1: None
        assert self.get_client_state(client_data) is None
        with pytest.raises(RuntimeError):
            client_data.mark_done()
        assert self.get_client_state(client_data) is None
        with pytest.raises(RuntimeError):
            client_data.mark_done_by_cancellation()
        assert self.get_client_state(client_data) is None
        with pytest.raises(RuntimeError):
            client_data.mark_running()
        assert self.get_client_state(client_data) is None

        ## Case 2: PENDING
        client_data.mark_pending()
        assert self.get_client_state(client_data) is _ClientState.TASK_PENDING
        with pytest.raises(RuntimeError):
            client_data.mark_pending()
        assert self.get_client_state(client_data) is _ClientState.TASK_PENDING
        with pytest.raises(RuntimeError):
            client_data.mark_done()
        assert self.get_client_state(client_data) is _ClientState.TASK_PENDING

        ## Case 3: RUNNING
        client_data.mark_running()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        with pytest.raises(RuntimeError):
            client_data.mark_pending()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        with pytest.raises(RuntimeError):
            client_data.mark_running()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        with pytest.raises(RuntimeError):
            client_data.mark_done_by_cancellation()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING

    def test____register_new_client_task____regular_state_transition(
        self,
        client_data: _ClientData,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level("ERROR")
        client_data.mark_pending()
        client_task_future: Future[None] = Future()

        # Act
        client_data.register_new_client_task(client_task_future)
        client_data.mark_running()
        client_task_future.set_result(None)

        # Assert
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        assert not caplog.records

    def test____register_new_client_task____regular_state_transition____task_cancelled(
        self,
        client_data: _ClientData,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level("ERROR")
        client_data.mark_pending()
        client_task_future: Future[None] = Future()

        # Act
        client_data.register_new_client_task(client_task_future)
        client_task_future.cancel()
        assert client_task_future.cancelled()

        # Assert
        assert self.get_client_state(client_data) is None
        assert not caplog.records

    def test____register_new_client_task____irregular_state_transition(
        self,
        client_data: _ClientData,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level("ERROR")
        client_task_future: Future[None]

        # Act & Assert
        ## Case 1: None
        client_task_future = Future()
        assert self.get_client_state(client_data) is None
        with pytest.raises(RuntimeError):
            client_data.register_new_client_task(client_task_future)
        assert self.get_client_state(client_data) is None
        client_task_future.cancel()
        assert client_task_future.cancelled()

        ## Case 2: RUNNING
        client_task_future = Future()
        client_data.mark_pending()
        client_data.mark_running()
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        with pytest.raises(RuntimeError):
            client_data.register_new_client_task(client_task_future)
        assert self.get_client_state(client_data) is _ClientState.TASK_RUNNING
        client_task_future.cancel()
        assert client_task_future.cancelled()

        # Assert
        assert not caplog.records

    def test____wait_for_new_packet____irregular_state_transition(
        self,
        client_data: _ClientData,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Arrange
        caplog.set_level("ERROR")
        client_task_future: Future[None] = Future()

        # Act & Assert
        ## Case 1: None
        assert self.get_client_state(client_data) is None
        with pytest.raises(RuntimeError):
            client_data.wait_for_new_packet(client_task_future, deadline=math.inf)

        ## Case 2: PENDING
        client_data.mark_pending()
        with pytest.raises(RuntimeError):
            client_data.wait_for_new_packet(client_task_future, deadline=math.inf)

    def test____wait_for_new_packet____irregular_state_transition____called_twice(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        client_data.mark_pending()
        client_data.mark_running()
        client_task_future: Future[None] = Future()
        client_data.wait_for_new_packet(client_task_future, deadline=math.inf)

        # Act & Assert
        with pytest.raises(RuntimeError):
            client_data.wait_for_new_packet(client_task_future, deadline=math.inf)

    def test____check_pending_task_timeout____no_pending_task(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        now: int = 12345

        # Act
        new_deadline = client_data.check_pending_task_timeout(now)

        # Assert
        assert new_deadline is math.inf

    def test____check_pending_task_timeout____pending_task_deadline_not_reached(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        now: int = 12345
        client_task_future: Future[None] = Future()

        client_data.mark_pending()
        client_data.mark_running()
        client_data.wait_for_new_packet(client_task_future, deadline=now + 10)

        # Act
        new_deadline = client_data.check_pending_task_timeout(now)

        # Assert
        assert not client_task_future.done()
        assert new_deadline == now + 10

    def test____check_pending_task_timeout____pending_task_deadline_reached(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        now: int = 12345
        client_task_future: Future[None] = Future()

        client_data.mark_pending()
        client_data.mark_running()
        client_data.wait_for_new_packet(client_task_future, deadline=now - 1)

        # Act
        new_deadline = client_data.check_pending_task_timeout(now)

        # Assert
        assert client_task_future.done()
        exc = client_task_future.exception()
        assert type(exc) is TimeoutError and exc.errno == errno.ETIMEDOUT
        assert new_deadline is math.inf

    def test____check_pending_task_timeout____pending_task_deadline_reached____task_cancelled(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        now: int = 12345
        client_task_future: Future[None] = Future()

        client_data.mark_pending()
        client_data.mark_running()
        client_data.wait_for_new_packet(client_task_future, deadline=now - 1)

        client_task_future.cancel()
        assert client_task_future.cancelled()

        # Act
        new_deadline = client_data.check_pending_task_timeout(now)

        # Assert
        assert new_deadline is math.inf

    def test____notify_client_task____no_pending_task(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        client_data.datagram_queue.put((b"data", None))

        # Act & Assert
        client_data.notify_client_task()

    def test____notify_client_task____empty_queue(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(RuntimeError):
            client_data.notify_client_task()

    def test____notify_client_task____pending_task_notified(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        client_data.datagram_queue.put((b"data", None))

        client_task_future: Future[None] = Future()

        client_data.mark_pending()
        client_data.mark_running()
        client_data.wait_for_new_packet(client_task_future, deadline=math.inf)

        # Act
        client_data.notify_client_task()

        # Assert
        assert client_task_future.done()
        assert client_task_future.result() is None

    def test____notify_client_task____pending_task_notified____task_cancelled_before(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        client_data.datagram_queue.put((b"data", None))

        client_task_future: Future[None] = Future()

        client_data.mark_pending()
        client_data.mark_running()
        client_data.wait_for_new_packet(client_task_future, deadline=math.inf)

        client_task_future.cancel()
        assert client_task_future.cancelled()

        # Act & Assert
        client_data.notify_client_task()

    def test____cancel_pending_task____no_pending_task(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange

        # Act & Assert
        client_data.cancel_pending_task()

    def test____cancel_pending_task____pending_task_notified(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        client_data.datagram_queue.put((b"data", None))

        client_task_future: Future[None] = Future()

        client_data.mark_pending()
        client_data.mark_running()
        client_data.wait_for_new_packet(client_task_future, deadline=math.inf)

        # Act
        client_data.cancel_pending_task()

        # Assert
        assert client_task_future.done() and client_task_future.cancelled()

    def test____cancel_pending_task____pending_task_notified____task_cancelled_before(
        self,
        client_data: _ClientData,
    ) -> None:
        # Arrange
        client_data.datagram_queue.put((b"data", None))

        client_task_future: Future[None] = Future()

        client_data.mark_pending()
        client_data.mark_running()
        client_data.wait_for_new_packet(client_task_future, deadline=math.inf)

        client_task_future.cancel()
        assert client_task_future.cancelled()

        # Act
        client_data.cancel_pending_task()

        # Assert
        assert client_task_future.done() and client_task_future.cancelled()
