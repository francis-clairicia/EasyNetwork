# -*- coding: Utf-8 -*-

from __future__ import annotations

import asyncio
from socket import socket as Socket
from typing import TYPE_CHECKING, Any, Iterator, final

from easynetwork.async_api.backend.abc import (
    AbstractAsyncBackend,
    AbstractAsyncDatagramServerAdapter,
    AbstractAsyncDatagramSocketAdapter,
    AbstractAsyncServerAdapter,
    AbstractAsyncStreamSocketAdapter,
    ILock,
)
from easynetwork.async_api.backend.factory import AsyncBackendFactory

import pytest

from ._fake_backends import FakeAsyncioBackend, FakeCurioBackend, FakeTrioBackend

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@final
class MockBackend(AbstractAsyncBackend):
    def __init__(self, mocker: MockerFixture) -> None:
        super().__init__()
        self.mock_coro_yield: MagicMock = mocker.MagicMock(side_effect=lambda: asyncio.sleep(0))

    async def coro_yield(self) -> None:
        await self.mock_coro_yield()

    async def create_tcp_connection(self, *args: Any, **kwargs: Any) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    async def wrap_tcp_socket(self, socket: Socket) -> AbstractAsyncStreamSocketAdapter:
        raise NotImplementedError

    async def create_tcp_server(self, *args: Any, **kwargs: Any) -> AbstractAsyncServerAdapter:
        raise NotImplementedError

    async def create_udp_endpoint(self, **kwargs: Any) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    async def wrap_udp_socket(self, socket: Socket) -> AbstractAsyncDatagramSocketAdapter:
        raise NotImplementedError

    async def create_udp_server(self, *args: Any, **kwargs: Any) -> AbstractAsyncDatagramServerAdapter:
        raise NotImplementedError

    def create_lock(self) -> ILock:
        raise NotImplementedError


@pytest.mark.asyncio
class TestAbstractAsyncBackend:
    @pytest.fixture
    @staticmethod
    def backend(mocker: MockerFixture) -> MockBackend:
        return MockBackend(mocker)

    async def test____wait_future____wait_until_done(
        self,
        backend: MockBackend,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from concurrent.futures import Future

        future: Future[Any] = Future()
        future.set_running_or_notify_cancel()
        task = asyncio.create_task(backend.wait_future(future))
        backend.mock_coro_yield.assert_not_called()

        # Act
        await asyncio.sleep(0)
        future.set_result(mocker.sentinel.result)
        await asyncio.sleep(0)
        assert task.done()
        result = task.result()

        # Assert
        backend.mock_coro_yield.assert_called_once_with()
        assert result is mocker.sentinel.result


class TestAsyncBackendFactory:
    BACKENDS: dict[str, type[AbstractAsyncBackend]] = {
        "asyncio": FakeAsyncioBackend,
        "trio": FakeTrioBackend,
        "curio": FakeCurioBackend,
    }

    @pytest.fixture(scope="class", autouse=True)
    @staticmethod
    def reset_factory_cache_at_end() -> Iterator[None]:
        # Drop after all tests are done in order not to impact next tests
        yield
        AsyncBackendFactory.invalidate_backends_cache()

        from easynetwork_asyncio import AsyncioBackend

        assert AsyncBackendFactory.get_all_backends() == {"asyncio": AsyncioBackend}

    @pytest.fixture(autouse=True)
    @staticmethod
    def setup_factory() -> Iterator[None]:
        AsyncBackendFactory.invalidate_backends_cache()
        yield
        AsyncBackendFactory.set_default_backend(None)

    @pytest.fixture(autouse=True)
    @classmethod
    def mock_importlib_metadata_entry_points(cls, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            "importlib.metadata.entry_points",
            autospec=True,
            return_value=list(map(cls.build_entry_point, cls.BACKENDS)),
        )

    @classmethod
    def build_entry_point(
        cls,
        name: str,
        value: str = "",
    ) -> EntryPoint:
        from importlib.metadata import EntryPoint

        if not value:
            try:
                _default_cls = cls.BACKENDS[name]
            except KeyError:
                _default_cls = MockBackend
            value = f"{_default_cls.__module__}:{_default_cls.__name__}"

        return EntryPoint(name, value, AsyncBackendFactory.GROUP_NAME)

    def test____get_all_backends____default(self) -> None:
        # Arrange

        # Act
        backends = AsyncBackendFactory.get_all_backends()

        # Assert
        assert backends == self.BACKENDS

    def test____get_all_backends____entry_point_is_module(self, mock_importlib_metadata_entry_points: MagicMock) -> None:
        # Arrange
        mock_importlib_metadata_entry_points.return_value = [
            self.build_entry_point("asyncio", __name__),
        ]

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid backend entry point \(name='asyncio'\): .+$"):
            AsyncBackendFactory.get_all_backends()

    def test____get_all_backends____entry_point_is_not_async_backend_class(
        self,
        mock_importlib_metadata_entry_points: MagicMock,
    ) -> None:
        # Arrange
        mock_importlib_metadata_entry_points.return_value = [
            self.build_entry_point("asyncio", "builtins:int"),
        ]

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid backend entry point \(name='asyncio'\): .+$"):
            AsyncBackendFactory.get_all_backends()

    def test____get_all_backends____entry_point_is_abstract(
        self,
        mock_importlib_metadata_entry_points: MagicMock,
    ) -> None:
        # Arrange
        mock_importlib_metadata_entry_points.return_value = [
            self.build_entry_point("asyncio", "easynetwork.async_api.backend.abc:AbstractAsyncBackend"),
        ]

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid backend entry point \(name='asyncio'\): .+$"):
            AsyncBackendFactory.get_all_backends()

    def test____get_all_backends____entry_point_module_not_found(
        self,
        mock_importlib_metadata_entry_points: MagicMock,
    ) -> None:
        # Arrange
        mock_importlib_metadata_entry_points.return_value = [
            self.build_entry_point("asyncio", "unknown_module:Backend"),
        ]

        # Act & Assert
        with pytest.raises(ModuleNotFoundError, match=r"^No module named 'unknown_module'$"):
            AsyncBackendFactory.get_all_backends()

    def test____get_all_backends____duplicate(
        self,
        mock_importlib_metadata_entry_points: MagicMock,
    ) -> None:
        # Arrange
        mock_importlib_metadata_entry_points.return_value = [
            self.build_entry_point("asyncio"),
            self.build_entry_point("asyncio"),
            self.build_entry_point("asyncio"),
        ]

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Conflicting backend name caught: 'asyncio'$"):
            AsyncBackendFactory.get_all_backends()

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____set_default_backend____from_string(self, backend_name: str) -> None:
        # Arrange

        # Act
        AsyncBackendFactory.set_default_backend(backend_name)

        # Assert
        assert AsyncBackendFactory.get_default_backend(guess_current_async_library=False) is self.BACKENDS[backend_name]

    def test____set_default_backend____from_string____unknown_backend(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(KeyError):
            AsyncBackendFactory.set_default_backend("unknown")

    @pytest.mark.parametrize("backend_cls", [*BACKENDS.values(), MockBackend])
    def test____set_default_backend____from_class(self, backend_cls: type[AbstractAsyncBackend]) -> None:
        # Arrange

        # Act
        AsyncBackendFactory.set_default_backend(backend_cls)

        # Assert
        assert AsyncBackendFactory.get_default_backend(guess_current_async_library=False) is backend_cls

    @pytest.mark.parametrize("invalid_cls", [int, Socket, TestAbstractAsyncBackend])
    def test____set_default_backend____from_class____error_do_not_derive_from_AbstractAsyncBackend(
        self,
        invalid_cls: type[Any],
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid backend class: %r$" % invalid_cls):
            AsyncBackendFactory.set_default_backend(invalid_cls)

    def test____set_default_backend____from_class____error_abstract_class_given(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Invalid backend class: %r$" % AbstractAsyncBackend):
            AsyncBackendFactory.set_default_backend(AbstractAsyncBackend)

    def test____get_default_backend____without_sniffio____returns_asyncio_backend(self) -> None:
        # Arrange
        AsyncBackendFactory.set_default_backend(None)

        # Act
        backend_cls = AsyncBackendFactory.get_default_backend(guess_current_async_library=False)

        # Assert
        assert backend_cls is FakeAsyncioBackend

    @pytest.mark.feature_sniffio
    @pytest.mark.parametrize("running_backend_name", list(BACKENDS))
    def test____get_default_backend____with_sniffio____returns_running_backend(
        self,
        running_backend_name: str,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_current_async_library: MagicMock = mocker.patch(
            "sniffio.current_async_library",
            autospec=True,
            return_value=running_backend_name,
        )
        AsyncBackendFactory.set_default_backend(None)

        # Act
        backend_cls = AsyncBackendFactory.get_default_backend(guess_current_async_library=True)

        # Assert
        mock_current_async_library.assert_called_once_with()
        assert backend_cls is self.BACKENDS[running_backend_name]

    @pytest.mark.feature_sniffio
    def test____get_default_backend____with_sniffio____running_library_does_not_have_backend_implementation(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_current_async_library: MagicMock = mocker.patch(
            "sniffio.current_async_library",
            autospec=True,
            return_value="some_other_async_runner",
        )
        AsyncBackendFactory.set_default_backend(None)

        # Act & Assert
        with pytest.raises(KeyError):
            AsyncBackendFactory.get_default_backend(guess_current_async_library=True)

        # Assert
        mock_current_async_library.assert_called_once_with()

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____new____instanciate_backend(self, backend_name: str) -> None:
        # Arrange

        # Act
        backend = AsyncBackendFactory.new(backend_name)

        # Assert
        assert isinstance(backend, self.BACKENDS[backend_name])

    def test____new____instanciate_default_backend(self, mocker: MockerFixture) -> None:
        # Arrange
        AsyncBackendFactory.set_default_backend(MockBackend)

        # Act
        backend = AsyncBackendFactory.new(mocker=mocker)

        # Assert
        assert isinstance(backend, MockBackend)
