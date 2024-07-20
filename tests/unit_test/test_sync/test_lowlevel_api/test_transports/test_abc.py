from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_sync.transports.abc import StreamTransport

import pytest

from ...._utils import make_recv_into_side_effect

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStreamTransport:
    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_time_perfcounter(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("time.perf_counter", autospec=True, return_value=12345)

    @pytest.fixture
    @staticmethod
    def mock_transport(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock(spec=StreamTransport)

    @pytest.fixture
    @staticmethod
    def mock_transport_send(mock_transport: MagicMock) -> MagicMock:
        mock_transport_send: MagicMock = mock_transport.send
        mock_transport_send.side_effect = lambda data, timeout: len(data)

        # send_all() will call send() with memoryviews and release the buffers after each call.
        # This is a workaround to use assert_called_with()
        mock_transport.send = lambda data, timeout: mock_transport_send(bytes(data), timeout)
        return mock_transport_send

    def test____recv____default(
        self,
        mock_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_transport.recv_into.side_effect = make_recv_into_side_effect(b"value")

        # Act
        data = StreamTransport.recv(mock_transport, 128, 123456879)

        # Assert
        assert type(data) is bytes
        assert data == b"value"
        mock_transport.recv_into.assert_called_once_with(mocker.ANY, 123456879)

    def test____recv____null_bufsize(
        self,
        mock_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_transport.recv_into.side_effect = make_recv_into_side_effect(b"never")

        # Act & Assert
        data = StreamTransport.recv(mock_transport, 0, 123456879)

        # Assert
        assert type(data) is bytes
        assert len(data) == 0
        mock_transport.recv_into.assert_not_called()

    def test____recv____invalid_bufsize_value(
        self,
        mock_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_transport.recv_into.side_effect = make_recv_into_side_effect(b"never")

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'bufsize' must be a positive or null integer$"):
            StreamTransport.recv(mock_transport, -1, 123456879)

        # Assert
        mock_transport.recv_into.assert_not_called()

    def test____recv____invalid_recv_into_return_value(
        self,
        mock_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_transport.recv_into.side_effect = [-1]

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^transport\.recv_into\(\) returned a negative value$"):
            StreamTransport.recv(mock_transport, 128, 123456879)

        # Assert
        mock_transport.recv_into.assert_called_once_with(mocker.ANY, 123456879)

    @pytest.mark.parametrize("data", [b"packet\n", b""], ids=repr)
    def test____send_all____one_shot_call(
        self,
        data: bytes,
        mock_transport: MagicMock,
        mock_transport_send: MagicMock,
    ) -> None:
        # Arrange

        # Act
        StreamTransport.send_all(mock_transport, data, 123456789)

        # Assert
        mock_transport_send.assert_called_once_with(data, 123456789)

    def test____send_all____several_call(
        self,
        mock_transport: MagicMock,
        mock_transport_send: MagicMock,
        mock_time_perfcounter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_transport_send.side_effect = [len(b"pack"), len(b"et"), len(b"\n")]
        now = 12345
        mock_time_perfcounter.side_effect = [
            now,
            now + 5,
            now + 5,
            now + 8,
            now + 8,
            now + 14,
        ]
        timeout: float = 123456789

        # Act
        StreamTransport.send_all(mock_transport, b"packet\n", timeout)

        # Assert
        assert mock_transport_send.call_args_list == [
            mocker.call(b"packet\n", timeout),
            mocker.call(b"et\n", timeout - 5),
            mocker.call(b"\n", timeout - 8),
        ]

    @pytest.mark.parametrize("data", [b"packet\n", b""], ids=repr)
    def test____send_all____invalid_send_return_value(
        self,
        data: bytes,
        mock_transport: MagicMock,
        mock_transport_send: MagicMock,
    ) -> None:
        # Arrange
        mock_transport_send.side_effect = [-1]

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^transport\.send\(\) returned a negative value$"):
            StreamTransport.send_all(mock_transport, data, 123456789)

        # Assert
        mock_transport_send.assert_called_once_with(data, 123456789)

    def test____send_all_from_iterable____concatenates_chunks_and_call_send_all(
        self,
        mock_transport: MagicMock,
        mock_time_perfcounter: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        now = 12345
        mock_time_perfcounter.side_effect = [
            now,
            now + 5,
        ]
        timeout: float = 123456789
        mock_transport.send_all.return_value = None
        chunks: list[bytes | bytearray | memoryview] = [b"a", bytearray(b"b"), memoryview(b"c")]

        # Act
        StreamTransport.send_all_from_iterable(mock_transport, chunks, 123456789)

        # Assert
        assert mock_transport.send_all.call_args_list == [
            mocker.call(b"abc", timeout),
        ]
