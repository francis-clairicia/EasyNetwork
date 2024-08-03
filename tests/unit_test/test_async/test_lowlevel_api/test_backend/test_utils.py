from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.backend._trio.backend import TrioBackend
from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend
from easynetwork.lowlevel.api_async.backend.utils import BuiltinAsyncBackendLiteral, ensure_backend, new_builtin_backend

import pytest

from ...._utils import mock_import_module_not_found

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_current_async_library(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("sniffio.current_async_library", autospec=True)


@pytest.mark.parametrize(
    ["name", "expected_type"],
    [
        pytest.param("asyncio", AsyncIOBackend, id="asyncio"),
        pytest.param("trio", TrioBackend, id="trio", marks=pytest.mark.feature_trio),
    ],
)
def test____ensure_backend____valid_string_literal(
    name: BuiltinAsyncBackendLiteral,
    expected_type: type[AsyncBackend],
    mock_current_async_library: MagicMock,
) -> None:
    # Arrange

    # Act
    backend = ensure_backend(name)

    # Assert
    assert isinstance(backend, expected_type)
    mock_current_async_library.assert_not_called()


def test____ensure_backend____already_a_backend_instance(mock_backend: MagicMock, mock_current_async_library: MagicMock) -> None:
    # Arrange

    # Act
    returned_backend = ensure_backend(mock_backend)

    # Assert
    assert returned_backend is mock_backend
    mock_current_async_library.assert_not_called()


def test____ensure_backend____type_error(mocker: MockerFixture, mock_current_async_library: MagicMock) -> None:
    # Arrange
    invalid_backend = mocker.MagicMock(spec=object)

    # Act & Assert
    with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .+$"):
        _ = ensure_backend(invalid_backend)
    mock_current_async_library.assert_not_called()


def test____ensure_backend____invalid_string_literal(mock_current_async_library: MagicMock) -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(NotImplementedError, match=r"^curio$"):
        _ = ensure_backend("curio")  # type: ignore[arg-type]
    mock_current_async_library.assert_not_called()


@pytest.mark.parametrize(
    ["name", "expected_type"],
    [
        pytest.param("asyncio", AsyncIOBackend, id="asyncio"),
        pytest.param("trio", TrioBackend, id="trio", marks=pytest.mark.feature_trio),
    ],
)
def test____ensure_backend____None____current_async_library_is_supported(
    name: BuiltinAsyncBackendLiteral,
    expected_type: type[AsyncBackend],
    mock_current_async_library: MagicMock,
) -> None:
    # Arrange
    mock_current_async_library.return_value = name

    # Act
    backend = ensure_backend(None)

    # Assert
    assert isinstance(backend, expected_type)
    mock_current_async_library.assert_called_once()


def test____ensure_backend____None____current_async_library_is_not_supported(mock_current_async_library: MagicMock) -> None:
    # Arrange
    mock_current_async_library.return_value = "curio"

    # Act & Assert
    with pytest.raises(NotImplementedError, match=r"^curio$"):
        _ = ensure_backend(None)
    mock_current_async_library.assert_called_once()


@pytest.mark.parametrize(
    ["name", "expected_type"],
    [
        pytest.param("asyncio", AsyncIOBackend, id="asyncio"),
        pytest.param("trio", TrioBackend, id="trio", marks=pytest.mark.feature_trio),
    ],
)
def test____new_builtin_backend____valid_string_literal(
    name: BuiltinAsyncBackendLiteral,
    expected_type: type[AsyncBackend],
) -> None:
    # Arrange

    # Act
    backend = new_builtin_backend(name)

    # Assert
    assert isinstance(backend, expected_type)


def test____new_builtin_backend____invalid_string_literal() -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(NotImplementedError, match=r"^curio$"):
        _ = ensure_backend("curio")  # type: ignore[arg-type]


def test____new_builtin_backend_____trio_dependency_missing(mocker: MockerFixture) -> None:
    # Arrange
    mock_import = mock_import_module_not_found({"trio"}, mocker)

    # Act
    with pytest.raises(ModuleNotFoundError) as exc_info:
        try:
            _ = new_builtin_backend("trio")
        finally:
            mocker.stop(mock_import)

    # Assert
    mock_import.assert_any_call("trio", mocker.ANY, mocker.ANY, None, 0)
    assert exc_info.value.args[0] == "trio dependencies are missing. Consider adding 'trio' extra"
    assert exc_info.value.__notes__ == ['example: pip install "easynetwork[trio]"']
    assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)
