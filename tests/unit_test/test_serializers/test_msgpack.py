from __future__ import annotations

from typing import TYPE_CHECKING, Any, final

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.msgpack import MessagePackerConfig, MessagePackSerializer, MessageUnpackerConfig

import pytest

from .._utils import mock_import_module_not_found
from .base import BaseSerializerConfigInstanceCheck

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@final
@pytest.mark.feature_msgpack
class TestMessagePackSerializer(BaseSerializerConfigInstanceCheck):
    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_cls() -> type[MessagePackSerializer]:
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

    def test____properties____right_values(self, debug_mode: bool) -> None:
        # Arrange

        # Act
        serializer = MessagePackSerializer(debug=debug_mode)

        # Assert
        assert serializer.debug is debug_mode

    def test____serialize____with_config(
        self,
        packer_config: MessagePackerConfig | None,
        mock_packb: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: MessagePackSerializer = MessagePackSerializer(packer_config=packer_config)
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

        serializer: MessagePackSerializer = MessagePackSerializer(unpacker_config=unpacker_config)
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
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import msgpack

        serializer: MessagePackSerializer = MessagePackSerializer(debug=debug_mode)
        mock_unpackb.side_effect = msgpack.OutOfData

        # Act & Assert
        with pytest.raises(DeserializeError, match=r"^Missing data to create packet$") as exc_info:
            serializer.deserialize(mocker.sentinel.data)

        # Assert
        assert isinstance(exc_info.value.__cause__, msgpack.OutOfData)
        if debug_mode:
            assert exc_info.value.error_info == {"data": mocker.sentinel.data}
        else:
            assert exc_info.value.error_info is None

    def test____deserialize____extra_data(
        self,
        mock_unpackb: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import msgpack

        serializer: MessagePackSerializer = MessagePackSerializer(debug=debug_mode)
        mock_unpackb.side_effect = msgpack.ExtraData(mocker.sentinel.packet, b"extra")

        # Act & Assert
        with pytest.raises(DeserializeError, match=r"^Extra data caught$") as exc_info:
            serializer.deserialize(mocker.sentinel.data)

        # Assert
        assert isinstance(exc_info.value.__cause__, msgpack.ExtraData)
        if debug_mode:
            assert exc_info.value.error_info == {"packet": mocker.sentinel.packet, "extra": b"extra"}
        else:
            assert exc_info.value.error_info is None

    def test____deserialize____any_exception_occurs(
        self,
        mock_unpackb: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: MessagePackSerializer = MessagePackSerializer(debug=debug_mode)
        mock_unpackb.side_effect = Exception

        # Act & Assert
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(mocker.sentinel.data)

        # Assert
        assert isinstance(exc_info.value.__cause__, Exception)
        if debug_mode:
            assert exc_info.value.error_info == {"data": mocker.sentinel.data}
        else:
            assert exc_info.value.error_info is None


class TestMessagePackSerializerDependencies:
    def test____dunder_init____msgpack_missing(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_import: MagicMock = mock_import_module_not_found({"msgpack"}, mocker)

        # Act
        with pytest.raises(ModuleNotFoundError) as exc_info:
            try:
                _ = MessagePackSerializer()
            finally:
                mocker.stop(mock_import)

        # Assert
        mock_import.assert_any_call("msgpack", mocker.ANY, mocker.ANY, None, 0)
        assert exc_info.value.args[0] == "message-pack dependencies are missing. Consider adding 'msgpack' extra"
        assert exc_info.value.__notes__ == ['example: pip install "easynetwork[msgpack]"']
        assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)

    def test____MessageUnpackerConfig____msgpack_missing(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_import: MagicMock = mock_import_module_not_found({"msgpack"}, mocker)

        # Act
        with pytest.raises(ModuleNotFoundError) as exc_info:
            try:
                _ = MessageUnpackerConfig()
            finally:
                mocker.stop(mock_import)

        # Assert
        mock_import.assert_any_call("msgpack", mocker.ANY, mocker.ANY, ("ExtType",), 0)
        assert exc_info.value.args[0] == "message-pack dependencies are missing. Consider adding 'msgpack' extra"
        assert exc_info.value.__notes__ == ['example: pip install "easynetwork[msgpack]"']
        assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)
