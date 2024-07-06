from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.backend.utils import ensure_backend

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_current_async_library(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("sniffio.current_async_library", autospec=True)


def test____ensure_backend____valid_string_literal(mock_current_async_library: MagicMock) -> None:
    # Arrange

    # Act
    backend = ensure_backend("asyncio")

    # Assert
    assert isinstance(backend, AsyncIOBackend)
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
    with pytest.raises(NotImplementedError, match=r"^trio$"):
        _ = ensure_backend("trio")  # type: ignore[arg-type]
    mock_current_async_library.assert_not_called()


def test____ensure_backend____None____current_async_library_is_supported(mock_current_async_library: MagicMock) -> None:
    # Arrange
    mock_current_async_library.return_value = "asyncio"

    # Act
    backend = ensure_backend(None)

    # Assert
    assert isinstance(backend, AsyncIOBackend)
    mock_current_async_library.assert_called_once()


def test____ensure_backend____None____current_async_library_is_not_supported(mock_current_async_library: MagicMock) -> None:
    # Arrange
    mock_current_async_library.return_value = "trio"

    # Act & Assert
    with pytest.raises(NotImplementedError, match=r"^trio$"):
        _ = ensure_backend(None)
    mock_current_async_library.assert_called_once()
