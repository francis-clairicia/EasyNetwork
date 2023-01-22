# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Generator, final

from easynetwork.converter import AbstractPacketConverter
from easynetwork.protocol import DatagramProtocol, StreamProtocol
from easynetwork.serializers.abc import AbstractPacketSerializer
from easynetwork.serializers.stream.abc import AbstractIncrementalPacketSerializer

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@final
class _PacketSerializerFixture(AbstractPacketSerializer[Any, Any]):
    def serialize(self, packet: Any) -> bytes:
        raise NotImplementedError

    def deserialize(self, data: bytes) -> Any:
        raise NotImplementedError


@final
class _IncrementalPacketSerializerFixture(AbstractIncrementalPacketSerializer[Any, Any]):
    def incremental_serialize(self, packet: Any) -> Generator[bytes, None, None]:
        raise NotImplementedError

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[Any, bytes]]:
        raise NotImplementedError


@final
class _PacketConverterFixture(AbstractPacketConverter[Any, Any, Any, Any]):
    def convert_to_dto_packet(self, obj: Any) -> Any:
        raise NotImplementedError

    def create_from_dto_packet(self, packet: Any) -> Any:
        raise NotImplementedError


@pytest.fixture
def mock_serializer_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec_set=_PacketSerializerFixture())


@pytest.fixture
def mock_serializer(mock_serializer_factory: Callable[[], Any]) -> Any:
    return mock_serializer_factory()


@pytest.fixture
def mock_incremental_serializer_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec_set=_IncrementalPacketSerializerFixture())


@pytest.fixture
def mock_incremental_serializer(mock_incremental_serializer_factory: Callable[[], Any]) -> Any:
    return mock_incremental_serializer_factory()


@pytest.fixture
def mock_converter_factory(mocker: MockerFixture) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec_set=_PacketConverterFixture())


@pytest.fixture
def mock_converter(mock_converter_factory: Callable[[], Any]) -> Any:
    return mock_converter_factory()


@pytest.fixture
def mock_datagram_protocol_factory(mocker: MockerFixture, mock_serializer_factory: Callable[[], Any]) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec_set=DatagramProtocol(mock_serializer_factory()))


@pytest.fixture
def mock_datagram_protocol(mock_datagram_protocol_factory: Callable[[], Any]) -> Any:
    return mock_datagram_protocol_factory()


@pytest.fixture
def mock_stream_protocol_factory(
    mocker: MockerFixture, mock_incremental_serializer_factory: Callable[[], Any]
) -> Callable[[], Any]:
    return lambda: mocker.NonCallableMagicMock(spec_set=StreamProtocol(mock_incremental_serializer_factory()))


@pytest.fixture
def mock_stream_protocol(mock_stream_protocol_factory: Callable[[], Any]) -> Any:
    return mock_stream_protocol_factory()
