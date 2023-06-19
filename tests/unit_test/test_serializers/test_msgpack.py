# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any, final

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.msgpack import MessagePackerConfig, MessagePackSerializer, MessageUnpackerConfig

import pytest

from .base import BaseSerializerConfigInstanceCheck

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@final
@pytest.mark.feature_msgpack
class TestMessagePackSerializer(BaseSerializerConfigInstanceCheck):
    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_cls() -> type[MessagePackSerializer[Any, Any]]:
        return MessagePackSerializer

    @pytest.fixture(params=["packer", "unpacker"])
    @staticmethod
    def config_param(request: Any) -> tuple[str, str]:
        name: str = request.param
        return (name, f"Message{name.capitalize()}Config")

    @pytest.fixture
    @staticmethod
    def mock_packb(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("msgpack.packb", autospec=True)

    @pytest.fixture
    @staticmethod
    def mock_unpackb(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("msgpack.unpackb", autospec=True)

    @pytest.fixture(params=[True, False], ids=lambda boolean: f"default_packer_config=={boolean}")
    @staticmethod
    def packer_config(request: Any, mocker: MockerFixture) -> MessagePackerConfig | None:
        use_default_config: bool = request.param
        if use_default_config:
            return None
        return MessagePackerConfig(
            default=mocker.sentinel.default,
            use_single_float=mocker.sentinel.use_single_float,
            use_bin_type=mocker.sentinel.use_bin_type,
            datetime=mocker.sentinel.datetime,
            strict_types=mocker.sentinel.strict_types,
            unicode_errors=mocker.sentinel.unicode_errors,
        )

    @pytest.fixture(params=[True, False], ids=lambda boolean: f"default_unpacker_config=={boolean}")
    @staticmethod
    def unpacker_config(request: Any, mocker: MockerFixture) -> MessageUnpackerConfig | None:
        use_default_config: bool = request.param
        if use_default_config:
            return None
        return MessageUnpackerConfig(
            raw=mocker.sentinel.raw,
            use_list=mocker.sentinel.use_list,
            timestamp=mocker.sentinel.timestamp,
            strict_map_key=mocker.sentinel.strict_map_key,
            unicode_errors=mocker.sentinel.unicode_errors,
            object_hook=mocker.sentinel.object_hook,
            object_pairs_hook=mocker.sentinel.object_pairs_hook,
            ext_hook=mocker.sentinel.ext_hook,
        )

    def test____serialize____with_config(
        self,
        packer_config: MessagePackerConfig | None,
        mock_packb: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: MessagePackSerializer[Any, Any] = MessagePackSerializer(packer_config=packer_config)
        mock_packb.return_value = mocker.sentinel.result

        # Act
        data = serializer.serialize(mocker.sentinel.packet)

        # Assert
        assert data is mocker.sentinel.result
        mock_packb.assert_called_once_with(
            mocker.sentinel.packet,
            default=mocker.sentinel.default if packer_config is not None else None,
            use_single_float=mocker.sentinel.use_single_float if packer_config is not None else False,
            use_bin_type=mocker.sentinel.use_bin_type if packer_config is not None else True,
            datetime=mocker.sentinel.datetime if packer_config is not None else False,
            strict_types=mocker.sentinel.strict_types if packer_config is not None else False,
            unicode_errors=mocker.sentinel.unicode_errors if packer_config is not None else "strict",
            autoreset=True,
        )

    def test____deserialize____with_config(
        self,
        unpacker_config: MessageUnpackerConfig | None,
        mock_unpackb: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import msgpack

        serializer: MessagePackSerializer[Any, Any] = MessagePackSerializer(unpacker_config=unpacker_config)
        mock_unpackb.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.deserialize(mocker.sentinel.data)

        # Assert
        assert packet is mocker.sentinel.packet
        mock_unpackb.assert_called_once_with(
            mocker.sentinel.data,
            raw=mocker.sentinel.raw if unpacker_config is not None else False,
            use_list=mocker.sentinel.use_list if unpacker_config is not None else True,
            timestamp=mocker.sentinel.timestamp if unpacker_config is not None else 0,
            strict_map_key=mocker.sentinel.strict_map_key if unpacker_config is not None else True,
            unicode_errors=mocker.sentinel.unicode_errors if unpacker_config is not None else "strict",
            object_hook=mocker.sentinel.object_hook if unpacker_config is not None else None,
            object_pairs_hook=mocker.sentinel.object_pairs_hook if unpacker_config is not None else None,
            ext_hook=mocker.sentinel.ext_hook if unpacker_config is not None else msgpack.ExtType,
        )

    def test____deserialize____missing_data(
        self,
        mock_unpackb: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import msgpack

        serializer: MessagePackSerializer[Any, Any] = MessagePackSerializer()
        mock_unpackb.side_effect = msgpack.OutOfData

        # Act & Assert
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(mocker.sentinel.data)

        # Assert
        assert isinstance(exc_info.value.__cause__, msgpack.OutOfData)
        assert exc_info.value.error_info == {"data": mocker.sentinel.data}

    def test____deserialize____extra_data(
        self,
        mock_unpackb: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import msgpack

        serializer: MessagePackSerializer[Any, Any] = MessagePackSerializer()
        mock_unpackb.side_effect = msgpack.ExtraData(mocker.sentinel.packet, b"extra")

        # Act & Assert
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(mocker.sentinel.data)

        # Assert
        assert isinstance(exc_info.value.__cause__, msgpack.ExtraData)
        assert exc_info.value.error_info == {"packet": mocker.sentinel.packet, "extra": b"extra"}

    def test____deserialize____any_exception_occurs(
        self,
        mock_unpackb: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: MessagePackSerializer[Any, Any] = MessagePackSerializer()
        mock_unpackb.side_effect = Exception

        # Act & Assert
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(mocker.sentinel.data)

        # Assert
        assert isinstance(exc_info.value.__cause__, Exception)
        assert exc_info.value.error_info == {"data": mocker.sentinel.data}
