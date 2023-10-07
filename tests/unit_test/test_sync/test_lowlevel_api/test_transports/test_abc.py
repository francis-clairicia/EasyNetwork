from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_sync.transports.abc import StreamTransport

import pytest

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
        mocker: MockerFixture,
        mock_time_perfcounter: MagicMock,
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
    ) -> None:
        # Arrange
        mock_transport.send_all.return_value = None
        chunks: list[bytes | bytearray | memoryview] = [b"a", bytearray(b"b"), memoryview(b"c")]

        # Act
        StreamTransport.send_all_from_iterable(mock_transport, chunks, 123456789)

        # Assert
        mock_transport.send_all.assert_called_once_with(b"abc", 123456789)
