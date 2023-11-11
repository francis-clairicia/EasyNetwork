from __future__ import annotations

import pickle
from io import BytesIO
from pickle import DEFAULT_PROTOCOL, Pickler, Unpickler
from typing import TYPE_CHECKING, Any, final

from easynetwork.exceptions import DeserializeError
from easynetwork.serializers.pickle import PicklerConfig, PickleSerializer, UnpicklerConfig

import pytest

from .base import BaseSerializerConfigInstanceCheck

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@final
class TestPickleSerializer(BaseSerializerConfigInstanceCheck):
    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_cls() -> type[PickleSerializer]:
        return PickleSerializer

    @pytest.fixture(params=["pickler", "unpickler"])
    @staticmethod
    def config_param(request: Any) -> tuple[str, str]:
        name: str = request.param
        return (name, f"{name.capitalize()}Config")

    @pytest.fixture
    @staticmethod
    def bytes_io(mocker: MockerFixture) -> BytesIO:
        file = BytesIO()

        def side_effect(initial_data: bytes = b"") -> BytesIO:
            file.seek(0)
            file.write(initial_data)
            file.seek(0)
            return file

        mocker.patch(f"{PickleSerializer.__module__}.BytesIO", side_effect=side_effect)
        return file

    @pytest.fixture
    @staticmethod
    def mock_pickler(bytes_io: BytesIO, mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=Pickler)

        def dump(obj: Any) -> None:
            bytes_io.write(str(obj).encode())

        mock.dump.side_effect = dump
        return mock

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_pickler_cls(mocker: MockerFixture, mock_pickler: MagicMock) -> MagicMock:
        return mocker.patch("pickle.Pickler", return_value=mock_pickler)

    @pytest.fixture
    @staticmethod
    def mock_unpickler(bytes_io: BytesIO, mocker: MockerFixture) -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=Unpickler)

        def load() -> Any:
            bytes_io.read()
            return mock.load.return_value

        mock.load.side_effect = load
        return mock

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_unpickler_cls(mocker: MockerFixture, mock_unpickler: MagicMock) -> MagicMock:
        return mocker.patch("pickle.Unpickler", return_value=mock_unpickler)

    @pytest.fixture(params=[True, False], ids=lambda boolean: f"default_pickler_config=={boolean}")
    @staticmethod
    def pickler_config(request: Any, mocker: MockerFixture) -> PicklerConfig | None:
        use_default_config: bool = request.param
        if use_default_config:
            return None
        return PicklerConfig(
            protocol=mocker.sentinel.pickle_protocol,
            fix_imports=mocker.sentinel.fix_imports,
        )

    @pytest.fixture(params=[True, False], ids=lambda boolean: f"default_unpickler_config=={boolean}")
    @staticmethod
    def unpickler_config(request: Any, mocker: MockerFixture) -> UnpicklerConfig | None:
        use_default_config: bool = request.param
        if use_default_config:
            return None
        return UnpicklerConfig(
            fix_imports=mocker.sentinel.fix_imports,
            encoding=mocker.sentinel.encoding,
            errors=mocker.sentinel.errors,
        )

    @pytest.fixture(params=[False, True], ids=lambda boolean: f"optimize=={boolean}")
    @staticmethod
    def pickler_optimize(request: Any) -> bool:
        return request.param

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_pickletools_optimize(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("pickletools.optimize", autospec=True)

    def test____properties____right_values(self, debug_mode: bool) -> None:
        # Arrange

        # Act
        serializer = PickleSerializer(debug=debug_mode)

        # Assert
        assert serializer.debug is debug_mode

    def test____serialize____with_config(
        self,
        pickler_optimize: bool,
        pickler_config: PicklerConfig | None,
        mock_pickler_cls: MagicMock,
        mock_pickler: MagicMock,
        mock_pickletools_optimize: MagicMock,
        bytes_io: BytesIO,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_pickletools_optimize.return_value = b"optimized pickle"
        serializer: PickleSerializer = PickleSerializer(
            pickler_config=pickler_config,
            pickler_optimize=pickler_optimize,
        )

        # Act
        data: bytes = serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_pickler_cls.assert_called_once_with(
            bytes_io,
            protocol=mocker.sentinel.pickle_protocol if pickler_config is not None else DEFAULT_PROTOCOL,
            fix_imports=mocker.sentinel.fix_imports if pickler_config is not None else False,
            buffer_callback=None,
        )
        if not pickler_optimize:
            assert data == str(mocker.sentinel.packet).encode()
            mock_pickletools_optimize.assert_not_called()
            mock_pickler.dump.assert_called_once_with(mocker.sentinel.packet)
        else:
            assert data == b"optimized pickle"
            mock_pickler.dump.assert_called_once_with(mocker.sentinel.packet)
            mock_pickletools_optimize.assert_called_once_with(str(mocker.sentinel.packet).encode())

    @pytest.mark.usefixtures("mock_pickletools_optimize")
    def test____serialize____custom_pickler_cls(
        self,
        pickler_optimize: bool,
        mock_pickler_cls: MagicMock,
        mock_pickler: MagicMock,
        bytes_io: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_other_pickler_cls: MagicMock = mocker.stub()
        mock_other_pickler: MagicMock = mock_other_pickler_cls.return_value
        serializer: PickleSerializer = PickleSerializer(
            pickler_cls=mock_other_pickler_cls,
            pickler_optimize=pickler_optimize,
        )
        del mock_pickler.dump

        # Act
        serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_pickler_cls.assert_not_called()
        mock_other_pickler_cls.assert_called_once_with(
            bytes_io,
            protocol=mocker.ANY,
            fix_imports=mocker.ANY,
            buffer_callback=mocker.ANY,
        )
        mock_other_pickler.dump.assert_called_once_with(mocker.sentinel.packet)

    def test____deserialize____with_config(
        self,
        unpickler_config: UnpicklerConfig | None,
        mock_unpickler_cls: MagicMock,
        mock_unpickler: MagicMock,
        bytes_io: BytesIO,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: PickleSerializer = PickleSerializer(unpickler_config=unpickler_config)
        mock_unpickler.load.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.deserialize(b"data")

        # Assert
        mock_unpickler_cls.assert_called_once_with(
            bytes_io,
            fix_imports=mocker.sentinel.fix_imports if unpickler_config is not None else False,
            encoding=mocker.sentinel.encoding if unpickler_config is not None else "utf-8",
            errors=mocker.sentinel.errors if unpickler_config is not None else "strict",
            buffers=None,
        )
        mock_unpickler.load.assert_called_once_with()
        assert packet is mocker.sentinel.packet

    def test____deserialize____custom_unpickler_cls(
        self,
        mock_unpickler_cls: MagicMock,
        mock_unpickler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_other_unpickler_cls: MagicMock = mocker.stub()
        mock_other_unpickler: MagicMock = mock_other_unpickler_cls.return_value
        serializer: PickleSerializer = PickleSerializer(unpickler_cls=mock_other_unpickler_cls)
        mock_other_unpickler.load.return_value = mocker.sentinel.packet
        del mock_unpickler.load

        # Act
        packet = serializer.deserialize(b"")

        # Assert
        mock_unpickler_cls.assert_not_called()
        mock_other_unpickler_cls.assert_called_once_with(
            mocker.ANY,
            fix_imports=mocker.ANY,
            encoding=mocker.ANY,
            errors=mocker.ANY,
            buffers=mocker.ANY,
        )
        mock_other_unpickler.load.assert_called_once_with()
        assert packet is mocker.sentinel.packet

    # Yes, pickle.Unpickler can raise a SystemError if the given data is invalid
    @pytest.mark.parametrize("exception", [pickle.UnpicklingError, ValueError, SystemError])
    def test____deserialize____deserialize_error(
        self,
        exception: type[BaseException],
        unpickler_config: UnpicklerConfig | None,
        mock_unpickler: MagicMock,
        debug_mode: bool,
    ) -> None:
        # Arrange
        serializer: PickleSerializer = PickleSerializer(unpickler_config=unpickler_config, debug=debug_mode)
        mock_unpickler.load.side_effect = exception()

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            serializer.deserialize(b"data")

        # Assert
        mock_unpickler.load.assert_called_once()
        assert exc_info.value.__cause__ is mock_unpickler.load.side_effect
        if debug_mode:
            assert exc_info.value.error_info == {"data": b"data"}
        else:
            assert exc_info.value.error_info is None

    def test____deserialize____extra_data(
        self,
        unpickler_config: UnpicklerConfig | None,
        mock_unpickler: MagicMock,
        bytes_io: BytesIO,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: PickleSerializer = PickleSerializer(unpickler_config=unpickler_config, debug=debug_mode)

        def unpickler_load() -> Any:
            assert bytes_io.read(2) == b"da"
            return mocker.sentinel.packet

        mock_unpickler.load.side_effect = unpickler_load

        # Act
        with pytest.raises(DeserializeError, match=r"^Extra data caught$") as exc_info:
            serializer.deserialize(b"data")

        # Assert
        mock_unpickler.load.assert_called_once()
        assert exc_info.value.__cause__ is None
        if debug_mode:
            assert exc_info.value.error_info == {"packet": mocker.sentinel.packet, "extra": b"ta"}
        else:
            assert exc_info.value.error_info is None
