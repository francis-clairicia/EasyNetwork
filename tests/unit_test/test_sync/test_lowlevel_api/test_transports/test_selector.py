from __future__ import annotations

import contextlib
import errno
import math
from collections.abc import Callable
from selectors import EVENT_READ, EVENT_WRITE, BaseSelector, SelectorKey
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_sync.transports.base_selector import (
    SelectorBaseTransport,
    SelectorDatagramTransport,
    SelectorStreamTransport,
    WouldBlockOnRead,
    WouldBlockOnWrite,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestSelectorBaseTransport:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_time_perfcounter(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("time.perf_counter", autospec=True, return_value=12345)

    @pytest.fixture
    @staticmethod
    def mock_selector(mocker: MockerFixture) -> MagicMock:
        mock_selector = mocker.NonCallableMagicMock(spec=BaseSelector)
        mock_selector.__enter__.return_value = mock_selector
        mock_selector.register.side_effect = lambda fd, events: SelectorKey(fd, fd, events, None)
        mock_selector.select.return_value = [mocker.sentinel.key]
        return mock_selector

    @pytest.fixture
    @staticmethod
    def mock_selector_register(mock_selector: MagicMock) -> MagicMock:
        return mock_selector.register

    @pytest.fixture
    @staticmethod
    def mock_selector_select(mock_selector: MagicMock) -> MagicMock:
        return mock_selector.select

    @pytest.fixture(params=[math.inf], ids=repr)
    @staticmethod
    def retry_interval(request: pytest.FixtureRequest) -> float:
        return request.param

    @pytest.fixture
    @staticmethod
    def mock_transport(retry_interval: float, mock_selector: MagicMock, mocker: MockerFixture) -> MagicMock:
        mock_transport = mocker.NonCallableMagicMock(spec=SelectorStreamTransport)
        SelectorBaseTransport.__init__(mock_transport, retry_interval, lambda: mock_selector)
        return mock_transport

    @pytest.mark.parametrize("retry_interval", [math.nan, -4, 0], ids=repr)
    def test____dunder_init____invalid_retry_interval(
        self,
        retry_interval: float,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_transport = mocker.NonCallableMagicMock(spec=SelectorBaseTransport)

        # Act & Assert
        with pytest.raises(ValueError):
            SelectorBaseTransport.__init__(mock_transport, retry_interval)

    def test____dunder_init____selector_factory____default_to_PollSelector(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_selector_cls = mocker.patch("selectors.PollSelector", create=True)
        mock_transport = mocker.NonCallableMagicMock(spec=SelectorBaseTransport)

        # Act
        SelectorBaseTransport.__init__(mock_transport, math.inf)

        # Assert
        assert mock_transport._selector_factory is mock_selector_cls

    def test____dunder_init____selector_factory____default_to_SelectSelector(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Arrange
        mock_selector_cls = mocker.patch("selectors.SelectSelector")
        mock_transport = mocker.NonCallableMagicMock(spec=SelectorBaseTransport)
        monkeypatch.delattr("selectors.PollSelector", raising=False)

        # Act
        SelectorBaseTransport.__init__(mock_transport, math.inf)

        # Assert
        assert mock_transport._selector_factory is mock_selector_cls

    @pytest.mark.parametrize("timeout", [math.nan, -4], ids=repr)
    def test____retry____invalid_timeout_value(
        self,
        timeout: float,
        mock_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        callback = mocker.stub()

        # Act & Assert
        with pytest.raises(ValueError):
            SelectorBaseTransport._retry(mock_transport, callback, timeout)

        callback.assert_not_called()

    @pytest.mark.parametrize(
        ["blocking_error", "selector_event"],
        [
            pytest.param(WouldBlockOnRead, EVENT_READ),
            pytest.param(WouldBlockOnWrite, EVENT_WRITE),
        ],
    )
    def test____retry____blocking_error(
        self,
        blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        selector_event: int,
        mock_transport: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        callback = mocker.stub()
        callback.side_effect = [blocking_error(mocker.sentinel.fd), mocker.sentinel.result]

        # Act
        result = SelectorBaseTransport._retry(mock_transport, callback, math.inf)

        # Assert
        assert callback.call_args_list == [mocker.call() for _ in range(2)]
        mock_selector_register.assert_called_once_with(mocker.sentinel.fd, selector_event)
        mock_selector_select.assert_called_once_with()
        assert result is mocker.sentinel.result

    @pytest.mark.parametrize(
        ["blocking_error", "selector_event"],
        [
            pytest.param(WouldBlockOnRead, EVENT_READ),
            pytest.param(WouldBlockOnWrite, EVENT_WRITE),
        ],
    )
    def test____retry____invalid_file_descriptor(
        self,
        blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        selector_event: int,
        mock_transport: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        callback = mocker.stub()
        callback.side_effect = [blocking_error(mocker.sentinel.fd), mocker.sentinel.result]
        mock_selector_register.side_effect = ValueError

        # Act & Assert
        with pytest.raises(OSError) as exc_info:
            SelectorBaseTransport._retry(mock_transport, callback, math.inf)

        # Assert
        callback.assert_called_once_with()
        mock_selector_register.assert_called_once_with(mocker.sentinel.fd, selector_event)
        mock_selector_select.assert_not_called()
        assert exc_info.value.errno == errno.EBADF
        assert isinstance(exc_info.value.__cause__, ValueError)

    @pytest.mark.parametrize(
        ["blocking_error", "selector_event"],
        [
            pytest.param(WouldBlockOnRead, EVENT_READ),
            pytest.param(WouldBlockOnWrite, EVENT_WRITE),
        ],
    )
    def test____retry____runtime_error_fd_not_available(
        self,
        blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        selector_event: int,
        mock_transport: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        callback = mocker.stub()
        callback.side_effect = [blocking_error(mocker.sentinel.fd), mocker.sentinel.result]
        mock_selector_select.side_effect = [[]]

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^timeout error with infinite timeout$"):
            SelectorBaseTransport._retry(mock_transport, callback, math.inf)

        # Assert
        callback.assert_called_once_with()
        mock_selector_register.assert_called_once_with(mocker.sentinel.fd, selector_event)
        mock_selector_select.assert_called_once_with()

    @pytest.mark.parametrize("blocking_error", [WouldBlockOnRead, WouldBlockOnWrite])
    def test____retry____null_timeout(
        self,
        blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        mock_transport: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        callback = mocker.stub()
        callback.side_effect = [blocking_error(mocker.sentinel.fd), mocker.sentinel.result]

        # Act & Assert
        with pytest.raises(TimeoutError):
            SelectorBaseTransport._retry(mock_transport, callback, 0.0)

        # Assert
        callback.assert_called_once_with()
        mock_selector_register.assert_not_called()
        mock_selector_select.assert_not_called()

    @pytest.mark.parametrize(
        ["blocking_error", "selector_event"],
        [
            pytest.param(WouldBlockOnRead, EVENT_READ),
            pytest.param(WouldBlockOnWrite, EVENT_WRITE),
        ],
    )
    @pytest.mark.parametrize("available", [False, True], ids=lambda p: f"available=={p}")
    @pytest.mark.parametrize("retry_interval", [math.inf, 5], ids=lambda p: f"retry_interval=={p}", indirect=True)
    def test____retry____timeout(
        self,
        blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        selector_event: int,
        available: bool,
        mock_transport: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_time_perfcounter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        callback = mocker.stub()
        callback.side_effect = [blocking_error(mocker.sentinel.fd), mocker.sentinel.result]
        if not available:
            mock_selector_select.return_value = []
        now = 12345
        timeout = 5
        mock_time_perfcounter.side_effect = [
            now,
            now + timeout,
        ]

        # Act
        result = None
        with pytest.raises(TimeoutError) if not available else contextlib.nullcontext():
            result = SelectorBaseTransport._retry(mock_transport, callback, timeout)

        # Assert
        mock_selector_register.assert_called_once_with(mocker.sentinel.fd, selector_event)
        mock_selector_select.assert_called_once_with(timeout)
        if available:
            assert callback.call_args_list == [mocker.call() for _ in range(2)]
            assert result is mocker.sentinel.result
        else:
            callback.assert_called_once_with()
            assert result is None

    @pytest.mark.parametrize(
        ["blocking_error", "selector_event"],
        [
            pytest.param(WouldBlockOnRead, EVENT_READ),
            pytest.param(WouldBlockOnWrite, EVENT_WRITE),
        ],
    )
    @pytest.mark.parametrize("available", [False, True], ids=lambda p: f"available=={p}")
    @pytest.mark.parametrize("retry_interval", [1], ids=lambda p: f"retry_interval=={p}", indirect=True)
    def test____retry____timeout____retry_interval(
        self,
        blocking_error: type[WouldBlockOnRead] | type[WouldBlockOnWrite],
        selector_event: int,
        available: bool,
        retry_interval: float,
        mock_transport: MagicMock,
        mock_selector_register: MagicMock,
        mock_selector_select: MagicMock,
        mock_time_perfcounter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        callback = mocker.stub()
        callback.side_effect = [
            blocking_error(mocker.sentinel.fd),
            blocking_error(mocker.sentinel.fd),
            blocking_error(mocker.sentinel.fd),
            mocker.sentinel.result,
        ]
        if not available:
            mock_selector_select.return_value = []
        mock_selector_select.side_effect = [[], [], mock_selector_select.return_value]
        now = 12345
        timeout = 2.5
        mock_time_perfcounter.side_effect = [
            now,
            now + retry_interval,
            now + retry_interval,
            now + retry_interval * 2,
            now + retry_interval * 2,
            now + retry_interval * 2 + 0.5,
        ]

        # Act
        result = None
        with pytest.raises(TimeoutError) if not available else contextlib.nullcontext():
            result = SelectorBaseTransport._retry(mock_transport, callback, timeout)

        # Assert
        assert mock_selector_register.call_args_list == [mocker.call(mocker.sentinel.fd, selector_event) for _ in range(3)]
        assert mock_selector_select.call_args_list == [mocker.call(retry_interval) for _ in range(2)] + [mocker.call(0.5)]
        if available:
            assert callback.call_args_list == [mocker.call() for _ in range(4)]
            assert result is mocker.sentinel.result
        else:
            assert callback.call_args_list == [mocker.call() for _ in range(3)]
            assert result is None


def _retry_side_effect(callback: Callable[[], Any], timeout: float) -> Any:
    while True:
        try:
            return callback()
        except (WouldBlockOnRead, WouldBlockOnWrite):
            pass


class TestSelectorStreamTransport:
    @pytest.fixture
    @staticmethod
    def mock_transport(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=SelectorStreamTransport)

    def test____recv____call_noblock_within_retry(
        self,
        mock_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_transport._retry.side_effect = _retry_side_effect
        mock_transport.recv_noblock.side_effect = [
            WouldBlockOnRead(mocker.sentinel.fd),
            WouldBlockOnWrite(mocker.sentinel.fd),
            mocker.sentinel.bytes,
        ]

        # Act
        data = SelectorStreamTransport.recv(mock_transport, mocker.sentinel.bufsize, mocker.sentinel.timeout)

        # Assert
        mock_transport._retry.assert_called_once_with(mocker.ANY, mocker.sentinel.timeout)
        assert mock_transport.recv_noblock.call_args_list == [mocker.call(mocker.sentinel.bufsize) for _ in range(3)]
        assert data is mocker.sentinel.bytes

    def test____send____call_noblock_within_retry(
        self,
        mock_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_transport._retry.side_effect = _retry_side_effect
        mock_transport.send_noblock.side_effect = [
            WouldBlockOnRead(mocker.sentinel.fd),
            WouldBlockOnWrite(mocker.sentinel.fd),
            mocker.sentinel.nb_sent_bytes,
        ]

        # Act
        sent = SelectorStreamTransport.send(mock_transport, mocker.sentinel.data, mocker.sentinel.timeout)

        # Assert
        mock_transport._retry.assert_called_once_with(mocker.ANY, mocker.sentinel.timeout)
        assert mock_transport.send_noblock.call_args_list == [mocker.call(mocker.sentinel.data) for _ in range(3)]
        assert sent is mocker.sentinel.nb_sent_bytes


class TestSelectorDatagramTransport:
    @pytest.fixture
    @staticmethod
    def mock_transport(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=SelectorDatagramTransport)

    def test____recv____call_noblock_within_retry(
        self,
        mock_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_transport._retry.side_effect = _retry_side_effect
        mock_transport.recv_noblock.side_effect = [
            WouldBlockOnRead(mocker.sentinel.fd),
            WouldBlockOnWrite(mocker.sentinel.fd),
            mocker.sentinel.bytes,
        ]

        # Act
        data = SelectorDatagramTransport.recv(mock_transport, mocker.sentinel.timeout)

        # Assert
        mock_transport._retry.assert_called_once_with(mocker.ANY, mocker.sentinel.timeout)
        assert mock_transport.recv_noblock.call_args_list == [mocker.call() for _ in range(3)]
        assert data is mocker.sentinel.bytes

    def test____send____call_noblock_within_retry(
        self,
        mock_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_transport._retry.side_effect = _retry_side_effect
        mock_transport.send_noblock.side_effect = [
            WouldBlockOnRead(mocker.sentinel.fd),
            WouldBlockOnWrite(mocker.sentinel.fd),
            None,
        ]

        # Act
        SelectorDatagramTransport.send(mock_transport, mocker.sentinel.data, mocker.sentinel.timeout)

        # Assert
        mock_transport._retry.assert_called_once_with(mocker.ANY, mocker.sentinel.timeout)
        assert mock_transport.send_noblock.call_args_list == [mocker.call(mocker.sentinel.data) for _ in range(3)]
