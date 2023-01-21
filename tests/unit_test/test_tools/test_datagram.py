# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from easynetwork.tools.datagram import DatagramConsumer, DatagramProducer

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestDatagramProducer:
    @pytest.fixture
    @staticmethod
    def producer(mock_datagram_protocol: MagicMock) -> DatagramProducer[Any, Any]:
        return DatagramProducer(mock_datagram_protocol)

    def test____dunder_iter____return_self(self, producer: DatagramProducer[Any, Any]) -> None:
        # Arrange

        # Act
        iterator = iter(producer)

        # Assert
        assert iterator is producer

    @pytest.fixture
    @staticmethod
    def packets(request: Any, mocker: MockerFixture) -> Any:
        return [getattr(mocker.sentinel, attr) for attr in request.param]

    @pytest.mark.parametrize(
        "packets",
        [
            pytest.param([], id="no packet"),
            pytest.param(["p1"], id="one packet"),
            pytest.param(["p1", "p2", "p3"], id="several packets"),
        ],
        indirect=True,
    )
    def test____dunder_next____serialize_queued_packets(
        self,
        packets: list[Any],
        producer: DatagramProducer[Any, Any],
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_make_datagram: MagicMock = mock_datagram_protocol.make_datagram
        mock_make_datagram.side_effect = lambda v: v
        producer.queue(mocker.sentinel.address, *packets)

        # Act
        datagrams: list[tuple[Any, Any]] = list(producer)

        # Assert
        assert mock_make_datagram.mock_calls == [mocker.call(p) for p in packets]
        assert datagrams == [(p, mocker.sentinel.address) for p in packets]

    def test____pending_packets____empty_producer(self, producer: DatagramProducer[Any, Any]) -> None:
        assert not producer.pending_packets()

    def test____pending_packets____queued_packet(self, producer: DatagramProducer[Any, Any], mocker: MockerFixture) -> None:
        producer.queue(mocker.sentinel.address, mocker.sentinel.packet)
        assert producer.pending_packets()

        next(producer)
        assert not producer.pending_packets()


class TestDatagramConsumer:
    @pytest.fixture
    @staticmethod
    def consumer(mock_datagram_protocol: MagicMock) -> DatagramConsumer[Any]:
        return DatagramConsumer(mock_datagram_protocol)

    def test____dunder_iter____return_self(self, consumer: DatagramConsumer[Any]) -> None:
        # Arrange

        # Act
        iterator = iter(consumer)

        # Assert
        assert iterator is consumer

    @pytest.mark.parametrize(
        "datagrams",
        [
            pytest.param([], id="no datagram"),
            pytest.param([b"d1"], id="one datagram"),
            pytest.param([b"d1", b"d2", b"d3"], id="several datagrams"),
        ],
    )
    def test____dunder_next____deserialize_queued_datagrams(
        self,
        datagrams: list[bytes],
        consumer: DatagramConsumer[Any],
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        packets: dict[bytes, Any] = {d: getattr(mocker.sentinel, d.decode("ascii")) for d in datagrams}
        mock_build_packet_from_datagram: MagicMock = mock_datagram_protocol.build_packet_from_datagram
        mock_build_packet_from_datagram.side_effect = lambda d, _a: packets[d]
        for _d in datagrams:
            consumer.queue(_d, mocker.sentinel.sender)

        # Act
        received_packets: list[tuple[Any, Any]] = list(consumer)

        # Assert
        assert mock_build_packet_from_datagram.mock_calls == [mocker.call(d, mocker.sentinel.sender) for d in datagrams]
        assert received_packets == [(packets[d], mocker.sentinel.sender) for d in datagrams]

    def test____pending_datagrams____empty_consumer(self, consumer: DatagramConsumer[Any]) -> None:
        assert not consumer.pending_datagrams()

    def test____pending_datagrams____queued_datagram(self, consumer: DatagramConsumer[Any], mocker: MockerFixture) -> None:
        consumer.queue(b"datagram", mocker.sentinel.sender)
        assert consumer.pending_datagrams()

        next(consumer)
        assert not consumer.pending_datagrams()
