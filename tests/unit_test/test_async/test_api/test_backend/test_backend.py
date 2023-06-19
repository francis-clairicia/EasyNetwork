# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from socket import socket as Socket
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Coroutine, Iterator, Literal, assert_never, final

from easynetwork.api_async.backend.abc import AbstractAsyncBackend
from easynetwork.api_async.backend.factory import AsyncBackendFactory

import pytest

from ._fake_backends import BaseFakeBackend, FakeAsyncioBackend, FakeCurioBackend, FakeTrioBackend

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@final
class MockBackend(BaseFakeBackend):
    def __init__(self, mocker: MockerFixture) -> None:
        super().__init__()
        self.mock_coro_yield: MagicMock = mocker.MagicMock(side_effect=lambda: asyncio.sleep(0))
        self.mock_current_time: MagicMock = mocker.MagicMock(return_value=123456789)
        self.mock_sleep = mocker.AsyncMock(return_value=None)

    async def coro_yield(self) -> None:
        await self.mock_coro_yield()

    async def cancel_shielded_coro_yield(self) -> None:
        await self.mock_coro_yield()

    def get_cancelled_exc_class(self) -> type[BaseException]:
        return asyncio.CancelledError

    def current_time(self) -> float:
        return self.mock_current_time()

    async def sleep(self, delay: float) -> None:
        return await self.mock_sleep(delay)

    async def ignore_cancellation(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        return await coroutine


@pytest.mark.asyncio
class TestAbstractAsyncBackend:
    @pytest.fixture
    @staticmethod
    def backend(mocker: MockerFixture) -> MockBackend:
        return MockBackend(mocker)

    async def test____sleep_until____sleep_deadline_offset(
        self,
        backend: MockBackend,
    ) -> None:
        # Arrange
        deadline: float = 234567891.05
        expected_sleep_time: float = deadline - backend.mock_current_time.return_value

        # Act
        await backend.sleep_until(deadline)

        # Assert
        backend.mock_current_time.assert_called_once_with()
        backend.mock_sleep.assert_awaited_once_with(pytest.approx(expected_sleep_time))

    async def test____sleep_until____deadline_lower_than_current_time(
        self,
        backend: MockBackend,
    ) -> None:
        # Arrange
        deadline: float = backend.mock_current_time.return_value - 220

        # Act
        await backend.sleep_until(deadline)

        # Assert
        backend.mock_current_time.assert_called_once_with()
        backend.mock_sleep.assert_awaited_once_with(0)


class TestAsyncBackendFactory:
    BACKENDS: MappingProxyType[str, type[AbstractAsyncBackend]] = MappingProxyType(
        {
            "asyncio": FakeAsyncioBackend,
            "trio": FakeTrioBackend,
            "curio": FakeCurioBackend,
        }
    )

    BACKEND_CLS_TO_NAME: MappingProxyType[type[AbstractAsyncBackend], str] = MappingProxyType({v: k for k, v in BACKENDS.items()})

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
        AsyncBackendFactory.remove_all_extensions()

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
            self.build_entry_point("asyncio", "easynetwork.api_async.backend.abc:AbstractAsyncBackend"),
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

    def test____get_available_backends____default(
        self,
        mock_importlib_metadata_entry_points: MagicMock,
    ) -> None:
        # Arrange
        mock_importlib_metadata_entry_points.return_value = [
            self.build_entry_point("asyncio"),
            self.build_entry_point("trio"),
            self.build_entry_point("curio"),
            self.build_entry_point("mock", f"{__name__}:MockBackend"),
        ]

        # Act
        available_backends = AsyncBackendFactory.get_available_backends()

        # Assert
        assert isinstance(available_backends, frozenset)
        assert available_backends == frozenset({"asyncio", "trio", "curio", "mock"})

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    @pytest.mark.parametrize("extended", [False, True], ids=lambda extended: f"extended=={extended}")
    def test____set_default_backend____from_string(self, backend_name: str, extended: bool) -> None:
        # Arrange
        expected_cls = self.BACKENDS[backend_name]
        if extended:

            class ExtendedBackend(self.BACKENDS[backend_name]):  # type: ignore[name-defined,misc]
                pass

            AsyncBackendFactory.extend(backend_name, ExtendedBackend)
            expected_cls = ExtendedBackend

        # Act
        AsyncBackendFactory.set_default_backend(backend_name)

        # Assert
        assert AsyncBackendFactory.get_default_backend(guess_current_async_library=False) is expected_cls

    def test____set_default_backend____from_string____unknown_backend(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(KeyError):
            AsyncBackendFactory.set_default_backend("unknown")

    @pytest.mark.parametrize("backend_cls", [*BACKENDS.values(), MockBackend])
    @pytest.mark.parametrize("extended", [False, True], ids=lambda extended: f"extended=={extended}")
    def test____set_default_backend____from_class(self, backend_cls: type[AbstractAsyncBackend], extended: bool) -> None:
        # Arrange
        if extended:
            try:
                _backend_name = self.BACKEND_CLS_TO_NAME[backend_cls]
            except KeyError:
                pytest.skip("Not an entry-point")

            class ExtendedBackend(backend_cls):  # type: ignore[valid-type,misc]
                pass

            AsyncBackendFactory.extend(_backend_name, ExtendedBackend)

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

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____extend____replace_by_a_subclass(self, backend_name: str) -> None:
        # Arrange
        class ExtendedBackend(self.BACKENDS[backend_name]):  # type: ignore[name-defined,misc]
            pass

        # Act
        AsyncBackendFactory.extend(backend_name, ExtendedBackend)

        # Assert
        assert AsyncBackendFactory.get_all_backends(extended=True)[backend_name] is ExtendedBackend
        assert AsyncBackendFactory.get_all_backends(extended=False)[backend_name] is self.BACKENDS[backend_name]

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    @pytest.mark.parametrize("method", ["using_None", "using_base_cls"])
    def test____extend____remove_extension(self, backend_name: str, method: Literal["using_None", "using_base_cls"]) -> None:
        # Arrange
        class ExtendedBackend(self.BACKENDS[backend_name]):  # type: ignore[name-defined,misc]
            pass

        AsyncBackendFactory.extend(backend_name, ExtendedBackend)
        assert AsyncBackendFactory.get_all_backends(extended=True)[backend_name] is ExtendedBackend

        # Act
        match method:
            case "using_None":
                AsyncBackendFactory.extend(backend_name, None)
            case "using_base_cls":
                AsyncBackendFactory.extend(backend_name, self.BACKENDS[backend_name])
            case _:
                assert_never(method)

        # Assert
        assert AsyncBackendFactory.get_all_backends(extended=True)[backend_name] is self.BACKENDS[backend_name]
        assert AsyncBackendFactory.get_all_backends(extended=False)[backend_name] is self.BACKENDS[backend_name]

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____extend____error_invalid_class(self, backend_name: str) -> None:
        # Arrange
        default_backend_cls = self.BACKENDS[backend_name]

        # Act & Assert
        with pytest.raises(
            TypeError, match=r"^Invalid backend class \(not a subclass of %r\): %r$" % (default_backend_cls, MockBackend)
        ):
            AsyncBackendFactory.extend(backend_name, MockBackend)

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____extend____several_replacement(self, backend_name: str) -> None:
        # Arrange
        class ExtendedBackendV1(self.BACKENDS[backend_name]):  # type: ignore[name-defined,misc]
            pass

        class ExtendedBackendV2(self.BACKENDS[backend_name]):  # type: ignore[name-defined,misc]
            pass

        # Act & Assert
        AsyncBackendFactory.extend(backend_name, ExtendedBackendV1)
        assert AsyncBackendFactory.get_all_backends(extended=True)[backend_name] is ExtendedBackendV1
        AsyncBackendFactory.extend(backend_name, ExtendedBackendV2)
        assert AsyncBackendFactory.get_all_backends(extended=True)[backend_name] is ExtendedBackendV2

    def test____get_default_backend____without_sniffio____returns_asyncio_backend(self) -> None:
        # Arrange
        AsyncBackendFactory.set_default_backend(None)

        # Act
        backend_cls = AsyncBackendFactory.get_default_backend(guess_current_async_library=False)

        # Assert
        assert backend_cls is FakeAsyncioBackend

    @pytest.mark.feature_sniffio
    @pytest.mark.parametrize("running_backend_name", list(BACKENDS))
    @pytest.mark.parametrize("extended", [False, True], ids=lambda extended: f"extended=={extended}")
    def test____get_default_backend____with_sniffio____returns_running_backend(
        self,
        running_backend_name: str,
        extended: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_cls = self.BACKENDS[running_backend_name]
        if extended:

            class ExtendedBackend(self.BACKENDS[running_backend_name]):  # type: ignore[name-defined,misc]
                pass

            AsyncBackendFactory.extend(running_backend_name, ExtendedBackend)
            expected_cls = ExtendedBackend

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
        assert backend_cls is expected_cls

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
    @pytest.mark.parametrize("extended", [False, True], ids=lambda extended: f"extended=={extended}")
    def test____new____instanciate_backend(self, backend_name: str, extended: bool) -> None:
        # Arrange
        expected_cls = self.BACKENDS[backend_name]
        if extended:

            class ExtendedBackend(self.BACKENDS[backend_name]):  # type: ignore[name-defined,misc]
                pass

            AsyncBackendFactory.extend(backend_name, ExtendedBackend)
            expected_cls = ExtendedBackend

        # Act
        backend = AsyncBackendFactory.new(backend_name)

        # Assert
        assert isinstance(backend, expected_cls)

    def test____new____instanciate_default_backend(self, mocker: MockerFixture) -> None:
        # Arrange
        AsyncBackendFactory.set_default_backend(MockBackend)

        # Act
        backend = AsyncBackendFactory.new(mocker=mocker)

        # Assert
        assert isinstance(backend, MockBackend)

    def test____ensure____return_given_backend_object(self, mocker: MockerFixture) -> None:
        # Arrange
        expected_backend = MockBackend(mocker)

        # Act
        backend = AsyncBackendFactory.ensure(expected_backend)

        # Assert
        assert backend is expected_backend

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    @pytest.mark.parametrize("backend_kwargs", [None, {}], ids=repr)
    def test____ensure____instanciate_backend_from_name(self, backend_name: str, backend_kwargs: dict[str, Any] | None) -> None:
        # Arrange

        # Act
        backend = AsyncBackendFactory.ensure(backend_name, backend_kwargs)

        # Assert
        assert isinstance(backend, self.BACKENDS[backend_name])

    def test____ensure____instanciate_default_backend(self, mocker: MockerFixture) -> None:
        # Arrange
        AsyncBackendFactory.set_default_backend(MockBackend)

        # Act
        backend = AsyncBackendFactory.ensure(None, {"mocker": mocker})

        # Assert
        assert isinstance(backend, MockBackend)
