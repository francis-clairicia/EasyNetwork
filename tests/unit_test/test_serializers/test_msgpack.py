from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any, final

from easynetwork.exceptions import DeserializeError
from easynetwork.lowlevel.constants import DEFAULT_SERIALIZER_LIMIT
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

    @pytest.fixture
    @staticmethod
    def mock_packer(mocker: MockerFixture) -> MagicMock:
        from msgpack import Packer

        return mocker.NonCallableMagicMock(spec=Packer)

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_packer_cls(mock_packer: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("msgpack.Packer", return_value=mock_packer)

    @pytest.fixture
    @staticmethod
    def mock_unpacker(mocker: MockerFixture) -> MagicMock:
        from msgpack import Unpacker

        return mocker.NonCallableMagicMock(spec=Unpacker, **{"tell.return_value": 0})

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_unpacker_cls(mock_unpacker: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("msgpack.Unpacker", return_value=mock_unpacker)

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

    @pytest.mark.parametrize(
        "method",
        [
            "incremental_serialize",
            "incremental_deserialize",
            "create_deserializer_buffer",
            "buffered_incremental_deserialize",
        ],
    )
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange
        from easynetwork.serializers.base_stream import FileBasedPacketSerializer

        # Act & Assert
        assert getattr(MessagePackSerializer, method) is getattr(FileBasedPacketSerializer, method)

    @pytest.mark.parametrize("limit", [147258369, None], ids=lambda p: f"limit=={p}")
    def test____properties____right_values(self, debug_mode: bool, limit: int | None) -> None:
        # Arrange

        # Act
        if limit is None:
            serializer = MessagePackSerializer(debug=debug_mode)
        else:
            serializer = MessagePackSerializer(debug=debug_mode, limit=limit)

        # Assert
        assert serializer.debug is debug_mode
        if limit is None:
            assert serializer.buffer_limit == DEFAULT_SERIALIZER_LIMIT
        else:
            assert serializer.buffer_limit == limit

    def test____serialize____with_config(
        self,
        packer_config: MessagePackerConfig | None,
        mock_packb: MagicMock,
        mock_packer_cls: MagicMock,
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
        mock_packer_cls.assert_not_called()

    def test____deserialize____with_config(
        self,
        unpacker_config: MessageUnpackerConfig | None,
        mock_unpackb: MagicMock,
        mock_unpacker_cls: MagicMock,
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
        mock_unpacker_cls.assert_not_called()

    def test____deserialize____missing_data(
        self,
        mock_unpackb: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: MessagePackSerializer = MessagePackSerializer(debug=debug_mode)
        mock_unpackb.side_effect = ValueError("Unpack failed: incomplete input")

        # Act & Assert
        with pytest.raises(DeserializeError, match=r"^Missing data to create packet$") as exc_info:
            serializer.deserialize(mocker.sentinel.data)

        # Assert
        assert isinstance(exc_info.value.__cause__, ValueError)
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

    def test____dump_to_file____with_config(
        self,
        packer_config: MessagePackerConfig | None,
        mock_packb: MagicMock,
        mock_packer_cls: MagicMock,
        mock_packer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: MessagePackSerializer = MessagePackSerializer(packer_config=packer_config)
        mock_packer.pack.side_effect = [b"msgpack-data"]
        mock_packb.side_effect = AssertionError

        # Act
        file = BytesIO()
        serializer.dump_to_file(mocker.sentinel.packet, file)

        # Assert
        assert file.getvalue() == b"msgpack-data"
        mock_packer_cls.assert_called_once_with(
            default=mocker.sentinel.default if packer_config is not None else None,
            use_single_float=mocker.sentinel.use_single_float if packer_config is not None else False,
            use_bin_type=mocker.sentinel.use_bin_type if packer_config is not None else True,
            datetime=mocker.sentinel.datetime if packer_config is not None else False,
            strict_types=mocker.sentinel.strict_types if packer_config is not None else False,
            unicode_errors=mocker.sentinel.unicode_errors if packer_config is not None else "strict",
            autoreset=True,
        )
        mock_packer.pack.assert_called_once_with(mocker.sentinel.packet)
        mock_packb.assert_not_called()

    @pytest.mark.parametrize("limit", [147258369, DEFAULT_SERIALIZER_LIMIT], ids=lambda p: f"limit=={p}")
    def test____load_from_file____with_config(
        self,
        limit: int,
        unpacker_config: MessageUnpackerConfig | None,
        mock_unpackb: MagicMock,
        mock_unpacker_cls: MagicMock,
        mock_unpacker: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        import msgpack

        serializer: MessagePackSerializer = MessagePackSerializer(unpacker_config=unpacker_config, limit=limit)
        mock_unpackb.side_effect = AssertionError

        def unpack_side_effect() -> Any:
            file.read()
            mock_unpacker.tell.return_value = file.tell()
            return mocker.sentinel.packet

        mock_unpacker.unpack.side_effect = unpack_side_effect

        # Act
        file = BytesIO(b"msgpack-data")
        packet = serializer.load_from_file(file)

        # Assert
        assert packet is mocker.sentinel.packet
        assert file.read() == b""
        mock_unpacker_cls.assert_called_once_with(
            file,
            raw=mocker.sentinel.raw if unpacker_config is not None else False,
            use_list=mocker.sentinel.use_list if unpacker_config is not None else True,
            timestamp=mocker.sentinel.timestamp if unpacker_config is not None else 0,
            strict_map_key=mocker.sentinel.strict_map_key if unpacker_config is not None else True,
            unicode_errors=mocker.sentinel.unicode_errors if unpacker_config is not None else "strict",
            object_hook=mocker.sentinel.object_hook if unpacker_config is not None else None,
            object_pairs_hook=mocker.sentinel.object_pairs_hook if unpacker_config is not None else None,
            ext_hook=mocker.sentinel.ext_hook if unpacker_config is not None else msgpack.ExtType,
            max_buffer_size=limit,
        )
        mock_unpacker.unpack.assert_called_once_with()
        mock_unpackb.assert_not_called()

    def test____load_from_file____missing_data(
        self,
        debug_mode: bool,
        mock_unpacker: MagicMock,
    ) -> None:
        # Arrange
        import msgpack

        serializer: MessagePackSerializer = MessagePackSerializer(debug=debug_mode)

        def unpack_side_effect() -> Any:
            file.read()
            mock_unpacker.tell.return_value = 0
            raise msgpack.OutOfData

        mock_unpacker.unpack.side_effect = unpack_side_effect

        # Act & Assert
        file = BytesIO(b"msgpack-data")
        with pytest.raises(EOFError):
            serializer.load_from_file(file)
        assert file.read() == b""

    def test____load_from_file____extra_data(
        self,
        debug_mode: bool,
        mock_unpacker: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: MessagePackSerializer = MessagePackSerializer(debug=debug_mode)

        def unpack_side_effect() -> Any:
            file.read()
            mock_unpacker.tell.return_value = len(b"msgpack-data")
            return mocker.sentinel.packet

        mock_unpacker.unpack.side_effect = unpack_side_effect

        # Act
        file = BytesIO(b"".join([b"msgpack-data", b"remaining_data"]))
        packet = serializer.load_from_file(file)

        # Assert
        assert packet is mocker.sentinel.packet
        assert file.read() == b"remaining_data"


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
