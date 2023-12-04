from __future__ import annotations

import sys

from easynetwork.lowlevel.api_async.backend._sniffio_helpers import _current_async_library_fallback

import pytest


def test____current_async_library_fallback____asyncio_not_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delitem(sys.modules, "asyncio", raising=False)

    # Act
    with pytest.raises(RuntimeError, match=r"^unknown async library, or not in async context$"):
        _current_async_library_fallback()

    # Assert
    assert "asyncio" not in sys.modules


def test____current_async_library_fallback____asyncio_not_running() -> None:
    # Arrange
    import asyncio

    del asyncio

    # Act & Assert
    with pytest.raises(RuntimeError, match=r"^unknown async library, or not in async context$"):
        _current_async_library_fallback()


def test____current_async_library_fallback____asyncio_is_running() -> None:
    # Arrange
    import asyncio

    async def main() -> str:
        return _current_async_library_fallback()

    # Act
    library_name = asyncio.run(main())

    # Assert
    assert library_name == "asyncio"
