from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Literal, assert_never

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.api_sync.transports.abc import (
    BaseTransport,
    DatagramReadTransport,
    DatagramTransport,
    DatagramWriteTransport,
    StreamReadTransport,
    StreamTransport,
    StreamWriteTransport,
)
from easynetwork.lowlevel.api_sync.transports.composite import StapledDatagramTransport, StapledStreamTransport

import pytest

from ...._utils import restore_mock_side_effect
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class BaseStapledTransportTests:

    def test____close____close_both_transports(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: BaseTransport,
    ) -> None:
        # Arrange
        assert not stapled_transport.is_closed()

        # Act
        stapled_transport.close()

        # Assert
        assert stapled_transport.is_closed()
        mock_send_transport.close.assert_called_once_with()
        mock_receive_transport.close.assert_called_once_with()

    @pytest.mark.parametrize("transport_cancelled", ["send", "receive"])
    def test____close____close_both_transports____even_upon_interrupt(
        self,
        transport_cancelled: Literal["send", "receive"],
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: BaseTransport,
    ) -> None:
        # Arrange
        match transport_cancelled:
            case "send":
                mock_send_transport.close.side_effect = KeyboardInterrupt
            case "receive":
                mock_receive_transport.close.side_effect = KeyboardInterrupt
            case _:
                assert_never(transport_cancelled)

        # Act
        with pytest.raises(KeyboardInterrupt):
            stapled_transport.close()

        # Assert
        mock_send_transport.close.assert_called_once_with()
        mock_receive_transport.close.assert_called_once_with()

    @pytest.mark.parametrize(
        ["send_transport_is_closed", "receive_transport_is_closed", "expected_state"],
        [
            pytest.param(False, False, False),
            pytest.param(True, False, False),
            pytest.param(False, True, False),
            pytest.param(True, True, True),
        ],
    )
    def test____is_closed____expected_state(
        self,
        send_transport_is_closed: bool,
        receive_transport_is_closed: bool,
        expected_state: bool,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: BaseTransport,
    ) -> None:
        # Arrange
        if send_transport_is_closed:
            mock_send_transport.close()
        if receive_transport_is_closed:
            mock_receive_transport.close()

        # Act
        is_closed = stapled_transport.is_closed()

        # Assert
        assert is_closed is expected_state

    def test____extra_attributes____both_transports_attributes(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: BaseTransport,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.extra_attributes = {
            mocker.sentinel.send_only_attr: lambda: mocker.sentinel.send_only_value,
            mocker.sentinel.attr_conflict: lambda: mocker.sentinel.send_won,
        }
        mock_receive_transport.extra_attributes = {
            mocker.sentinel.recv_only_attr: lambda: mocker.sentinel.recv_only_value,
            mocker.sentinel.attr_conflict: lambda: mocker.sentinel.recv_won,
        }

        # Act & Assert
        assert stapled_transport.extra(mocker.sentinel.send_only_attr) is mocker.sentinel.send_only_value
        assert stapled_transport.extra(mocker.sentinel.recv_only_attr) is mocker.sentinel.recv_only_value
        assert stapled_transport.extra(mocker.sentinel.attr_conflict) is mocker.sentinel.recv_won


class TestStapledStreamTransport(BaseStapledTransportTests):
    @pytest.fixture(params=[StreamWriteTransport, StreamTransport])
    @staticmethod
    def mock_send_transport(
        request: pytest.FixtureRequest,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=request.param)

    @pytest.fixture(params=[StreamReadTransport, StreamTransport])
    @staticmethod
    def mock_receive_transport(
        request: pytest.FixtureRequest,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=request.param)

    @pytest.fixture
    @staticmethod
    def stapled_transport(
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
    ) -> Iterator[StapledStreamTransport[MagicMock, MagicMock]]:
        transport = StapledStreamTransport(mock_send_transport, mock_receive_transport)
        mock_send_transport.reset_mock()
        mock_receive_transport.reset_mock()
        with transport:
            with restore_mock_side_effect(mock_send_transport.close), restore_mock_side_effect(mock_receive_transport.close):
                yield transport

    def test____recv____calls_receive_transport_recv(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: StapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_receive_transport.recv.return_value = mocker.sentinel.recv_result

        # Act
        data = stapled_transport.recv(mocker.sentinel.recv_bufsize, mocker.sentinel.recv_timeout)

        # Assert
        assert data is mocker.sentinel.recv_result
        assert mock_receive_transport.mock_calls == [
            mocker.call.recv(mocker.sentinel.recv_bufsize, mocker.sentinel.recv_timeout),
        ]
        assert mock_send_transport.mock_calls == []

    def test____recv_into____calls_receive_transport_recv_into(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: StapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_receive_transport.recv_into.return_value = mocker.sentinel.recv_into_result

        # Act
        nbytes = stapled_transport.recv_into(mocker.sentinel.recv_buffer, mocker.sentinel.recv_timeout)

        # Assert
        assert nbytes is mocker.sentinel.recv_into_result
        assert mock_receive_transport.mock_calls == [
            mocker.call.recv_into(mocker.sentinel.recv_buffer, mocker.sentinel.recv_timeout),
        ]
        assert mock_send_transport.mock_calls == []

    def test____send____calls_send_transport_send(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: StapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.send.return_value = mocker.sentinel.send_result

        # Act
        nbytes = stapled_transport.send(mocker.sentinel.send_data, mocker.sentinel.send_timeout)

        # Assert
        assert nbytes is mocker.sentinel.send_result
        assert mock_send_transport.mock_calls == [
            mocker.call.send(mocker.sentinel.send_data, mocker.sentinel.send_timeout),
        ]
        assert mock_receive_transport.mock_calls == []

    def test____send_all____calls_send_transport_send_all(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: StapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.send_all.return_value = None

        # Act
        stapled_transport.send_all(mocker.sentinel.send_data, mocker.sentinel.send_timeout)

        # Assert
        assert mock_send_transport.mock_calls == [
            mocker.call.send_all(mocker.sentinel.send_data, mocker.sentinel.send_timeout),
        ]
        assert mock_receive_transport.mock_calls == []

    def test____send_all_from_iterable____calls_send_transport_send_all_from_iterable(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: StapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.send_all_from_iterable.return_value = None

        # Act
        stapled_transport.send_all_from_iterable(mocker.sentinel.send_data, mocker.sentinel.send_timeout)

        # Assert
        assert mock_send_transport.mock_calls == [
            mocker.call.send_all_from_iterable(mocker.sentinel.send_data, mocker.sentinel.send_timeout),
        ]
        assert mock_receive_transport.mock_calls == []

    def test____send_eof____calls_send_transport_send_eof_if_exists_else_close(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: StapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if hasattr(mock_send_transport, "send_eof"):
            mock_send_transport.send_eof.return_value = None

        # Act
        stapled_transport.send_eof()

        # Assert
        if hasattr(mock_send_transport, "send_eof"):
            assert mock_send_transport.mock_calls == [mocker.call.send_eof()]
        else:
            assert mock_send_transport.mock_calls == [mocker.call.close()]
        assert mock_receive_transport.mock_calls == []

    @pytest.mark.parametrize("mock_send_transport", [StreamTransport], indirect=True)
    @pytest.mark.parametrize("send_eof_error", [UnsupportedOperation, NotImplementedError])
    def test____send_eof____calls_send_transport_aclos_if_send_eof_is_not_implemented(
        self,
        send_eof_error: type[Exception],
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: StapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.send_eof.side_effect = send_eof_error

        # Act
        stapled_transport.send_eof()

        # Assert
        assert mock_send_transport.mock_calls == [mocker.call.send_eof(), mocker.call.close()]
        assert mock_receive_transport.mock_calls == []


class TestStapledDatagramTransport(BaseStapledTransportTests):
    @pytest.fixture(params=[DatagramWriteTransport, DatagramTransport])
    @staticmethod
    def mock_send_transport(
        request: pytest.FixtureRequest,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=request.param)

    @pytest.fixture(params=[DatagramReadTransport, DatagramTransport])
    @staticmethod
    def mock_receive_transport(
        request: pytest.FixtureRequest,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=request.param)

    @pytest.fixture
    @staticmethod
    def stapled_transport(
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
    ) -> Iterator[StapledDatagramTransport[MagicMock, MagicMock]]:
        transport = StapledDatagramTransport(mock_send_transport, mock_receive_transport)
        mock_send_transport.reset_mock()
        mock_receive_transport.reset_mock()
        with transport:
            with restore_mock_side_effect(mock_send_transport.close), restore_mock_side_effect(mock_receive_transport.close):
                yield transport

    def test____recv____calls_receive_transport_recv(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: StapledDatagramTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_receive_transport.recv.return_value = mocker.sentinel.recv_result

        # Act
        data = stapled_transport.recv(mocker.sentinel.recv_timeout)

        # Assert
        assert data is mocker.sentinel.recv_result
        assert mock_receive_transport.mock_calls == [
            mocker.call.recv(mocker.sentinel.recv_timeout),
        ]
        assert mock_send_transport.mock_calls == []

    def test____send____calls_send_transport_send(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: StapledDatagramTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.send.return_value = None

        # Act
        stapled_transport.send(mocker.sentinel.send_data, mocker.sentinel.send_timeout)

        # Assert
        assert mock_send_transport.mock_calls == [
            mocker.call.send(mocker.sentinel.send_data, mocker.sentinel.send_timeout),
        ]
        assert mock_receive_transport.mock_calls == []
