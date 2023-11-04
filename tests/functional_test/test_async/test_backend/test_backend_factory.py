from __future__ import annotations

from collections.abc import Iterator

from easynetwork.lowlevel.api_async.backend.factory import AsyncBackendFactory

import pytest


class TestAsyncBackendFactory:
    @pytest.fixture(autouse=True)
    @staticmethod
    def setup_factory() -> Iterator[None]:
        AsyncBackendFactory.invalidate_backends_cache()
        yield
        AsyncBackendFactory.set_default_backend(None)

    def test____get_available_backends____imports_asyncio_backend(self) -> None:
        assert AsyncBackendFactory.get_available_backends() == frozenset({"asyncio"})

    def test____get_all_backends____imports_asyncio_backend(self) -> None:
        from easynetwork.lowlevel.asyncio import AsyncIOBackend

        assert AsyncBackendFactory.get_all_backends() == {"asyncio": AsyncIOBackend}

    def test____get_default_backend____returns_asyncio_backend(self) -> None:
        from easynetwork.lowlevel.asyncio import AsyncIOBackend

        assert AsyncBackendFactory.get_default_backend(guess_current_async_library=False) is AsyncIOBackend

    def test____new____returns_asyncio_backend_instance(self) -> None:
        from easynetwork.lowlevel.asyncio import AsyncIOBackend

        backend = AsyncBackendFactory.new("asyncio")

        assert isinstance(backend, AsyncIOBackend)
