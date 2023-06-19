# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Iterator

from easynetwork.api_async.backend.factory import AsyncBackendFactory

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
        from easynetwork_asyncio import AsyncioBackend

        assert AsyncBackendFactory.get_all_backends() == {"asyncio": AsyncioBackend}

    def test____get_default_backend____returns_asyncio_backend(self) -> None:
        from easynetwork_asyncio import AsyncioBackend

        assert AsyncBackendFactory.get_default_backend(guess_current_async_library=False) is AsyncioBackend

    def test____new____returns_asyncio_backend_instance(self) -> None:
        from easynetwork_asyncio import AsyncioBackend

        backend = AsyncBackendFactory.new("asyncio")

        assert isinstance(backend, AsyncioBackend)
