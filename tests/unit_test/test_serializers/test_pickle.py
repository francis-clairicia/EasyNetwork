# -*- coding: Utf-8 -*

from __future__ import annotations

from pickle import DEFAULT_PROTOCOL, Pickler, Unpickler
from typing import TYPE_CHECKING, Any, final

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
    def serializer_cls() -> type[PickleSerializer[Any, Any]]:
        return PickleSerializer

    @pytest.fixture(params=["pickler", "unpickler"])
    @staticmethod
    def config_param(request: Any) -> tuple[str, str]:
        name: str = request.param
        return (name, f"{name.capitalize()}Config")

    @pytest.fixture
    @staticmethod
    def mock_pickler(mocker: MockerFixture) -> MagicMock:
        return mocker.MagicMock(spec=Pickler)

    @pytest.fixture
    @staticmethod
    def mock_pickler_cls(mocker: MockerFixture, mock_pickler: MagicMock) -> MagicMock:
        return mocker.patch("pickle.Pickler", return_value=mock_pickler)

    @pytest.fixture
    @staticmethod
    def mock_unpickler(mocker: MockerFixture) -> MagicMock:
        return mocker.MagicMock(spec=Unpickler)

    @pytest.fixture
    @staticmethod
    def mock_unpickler_cls(mocker: MockerFixture, mock_unpickler: MagicMock) -> MagicMock:
        return mocker.patch("pickle.Unpickler", return_value=mock_unpickler)

    @pytest.fixture
    @staticmethod
    def mock_file(mocker: MockerFixture) -> MagicMock:
        from io import BytesIO

        return mocker.MagicMock(spec=BytesIO)

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

    @pytest.fixture
    @staticmethod
    def mock_pickletools_optimize(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("pickletools.optimize", autospec=True)

    @pytest.mark.parametrize("method", ["serialize", "incremental_serialize", "deserialize", "incremental_deserialize"])
    def test____base_class____implements_default_methods(self, method: str) -> None:
        # Arrange
        from easynetwork.serializers.base_stream import FileBasedIncrementalPacketSerializer

        # Act & Assert
        assert getattr(PickleSerializer, method) is getattr(FileBasedIncrementalPacketSerializer, method)

    def test____dump_to_file____with_config(
        self,
        pickler_optimize: bool,
        pickler_config: PicklerConfig | None,
        mock_pickler_cls: MagicMock,
        mock_pickler: MagicMock,
        mock_file: MagicMock,
        mock_pickletools_optimize: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_pickletools_optimize.return_value = mocker.sentinel.optimized_pickle
        serializer: PickleSerializer[Any, Any] = PickleSerializer(pickler_config=pickler_config, optimize=pickler_optimize)

        # Act
        serializer.dump_to_file(mocker.sentinel.packet, mock_file)

        # Assert
        if not pickler_optimize:
            mock_pickler_cls.assert_called_once_with(
                mock_file,
                protocol=mocker.sentinel.pickle_protocol if pickler_config is not None else DEFAULT_PROTOCOL,
                fix_imports=mocker.sentinel.fix_imports if pickler_config is not None else False,
                buffer_callback=None,
            )
            mock_pickletools_optimize.assert_not_called()
            mock_pickler.dump.assert_called_once_with(mocker.sentinel.packet)
        else:
            mock_pickler_cls.assert_called_once_with(
                mocker.ANY,
                protocol=mocker.sentinel.pickle_protocol if pickler_config is not None else DEFAULT_PROTOCOL,
                fix_imports=mocker.sentinel.fix_imports if pickler_config is not None else False,
                buffer_callback=None,
            )
            mock_pickler.dump.assert_called_once_with(mocker.sentinel.packet)
            mock_pickletools_optimize.assert_called_once_with(mocker.ANY)
            mock_file.write.assert_called_once_with(mocker.sentinel.optimized_pickle)

    @pytest.mark.usefixtures("mock_pickletools_optimize")
    def test____dump_to_file____custom_pickler_cls(
        self,
        pickler_optimize: bool,
        mock_pickler_cls: MagicMock,
        mock_pickler: MagicMock,
        mock_file: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_other_pickler_cls: MagicMock = mocker.MagicMock(spec=Pickler)
        mock_other_pickler: MagicMock = mock_other_pickler_cls.return_value
        serializer: PickleSerializer[Any, Any] = PickleSerializer(pickler_cls=mock_other_pickler_cls, optimize=pickler_optimize)
        del mock_pickler.dump

        # Act
        serializer.dump_to_file(mocker.sentinel.packet, mock_file)

        # Assert
        mock_pickler_cls.assert_not_called()
        mock_other_pickler_cls.assert_called_once_with(
            mocker.ANY,
            protocol=mocker.ANY,
            fix_imports=mocker.ANY,
            buffer_callback=mocker.ANY,
        )
        mock_other_pickler.dump.assert_called_once_with(mocker.sentinel.packet)

    def test____load_from_file____with_config(
        self,
        unpickler_config: UnpicklerConfig | None,
        mock_unpickler_cls: MagicMock,
        mock_unpickler: MagicMock,
        mock_file: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: PickleSerializer[Any, Any] = PickleSerializer(unpickler_config=unpickler_config)
        mock_unpickler.load.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.load_from_file(mock_file)

        # Assert
        mock_unpickler_cls.assert_called_once_with(
            mock_file,
            fix_imports=mocker.sentinel.fix_imports if unpickler_config is not None else False,
            encoding=mocker.sentinel.encoding if unpickler_config is not None else "utf-8",
            errors=mocker.sentinel.errors if unpickler_config is not None else "strict",
            buffers=None,
        )
        mock_unpickler.load.assert_called_once_with()
        assert packet is mocker.sentinel.packet

    def test____load_from_file____custom_unpickler_cls(
        self,
        mock_unpickler_cls: MagicMock,
        mock_unpickler: MagicMock,
        mock_file: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_other_unpickler_cls: MagicMock = mocker.MagicMock(spec=Unpickler)
        mock_other_unpickler: MagicMock = mock_other_unpickler_cls.return_value
        serializer: PickleSerializer[Any, Any] = PickleSerializer(unpickler_cls=mock_other_unpickler_cls)
        mock_other_unpickler.load.return_value = mocker.sentinel.packet
        del mock_unpickler.load

        # Act
        packet = serializer.load_from_file(mock_file)

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
