from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Iterator
from socket import socket as Socket
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, assert_never, final

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend
from easynetwork.lowlevel.api_async.backend.factory import AsyncBackendFactory

import pytest

from ._fake_backends import BaseFakeBackend, FakeAsyncIOBackend, FakeCurioBackend, FakeTrioBackend

if TYPE_CHECKING:
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
class TestAsyncBackend:
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
    BACKENDS: MappingProxyType[str, type[AsyncBackend]] = MappingProxyType(
        {
            "asyncio": FakeAsyncIOBackend,
            "trio": FakeTrioBackend,
            "curio": FakeCurioBackend,
        }
    )

    BACKEND_CLS_TO_NAME: MappingProxyType[type[AsyncBackend], str] = MappingProxyType({v: k for k, v in BACKENDS.items()})

    CURRENT_ASYNC_LIBRARY_FUNC: str = "easynetwork.lowlevel.api_async.backend._sniffio_helpers.current_async_library"

    @pytest.fixture(scope="class", autouse=True)
    @staticmethod
    def reset_factory_cache_at_end() -> Iterator[None]:
        # Drop after all tests are done in order not to impact next tests
        yield
        AsyncBackendFactory.invalidate_backends_cache()
        AsyncBackendFactory.remove_installed_hooks()

    @pytest.fixture(autouse=True)
    @classmethod
    def setup_factory(cls) -> None:
        AsyncBackendFactory.remove_installed_hooks()
        for backend_name, backend_cls in cls.BACKENDS.items():
            AsyncBackendFactory.push_backend_factory(backend_name, backend_cls)

    def test____push_factory_hook____not_callable(self, mocker: MockerFixture) -> None:
        # Arrange
        obj = mocker.NonCallableMock()

        # Act & Assert
        with pytest.raises(TypeError, match=r"^.+ is not callable$"):
            AsyncBackendFactory.push_factory_hook(obj)

    def test____push_backend_factory____not_callable(self, mocker: MockerFixture) -> None:
        # Arrange
        obj = mocker.NonCallableMock()

        # Act & Assert
        with pytest.raises(TypeError, match=r"^.+ is not callable$"):
            AsyncBackendFactory.push_backend_factory("mock", obj)

    def test____push_backend_factory____backend_is_not_a_string(self, mocker: MockerFixture) -> None:
        # Arrange
        factory = mocker.stub()

        # Act & Assert
        with pytest.raises(TypeError, match=r"^backend_name: Expected a string$"):
            AsyncBackendFactory.push_backend_factory(4, factory)  # type: ignore[arg-type]

    @pytest.mark.parametrize("invalid_token", ["", "   ", "\nasyncio", "asyncio\t"], ids=repr)
    def test____push_backend_factory____backend_string_is_invalid(self, invalid_token: str, mocker: MockerFixture) -> None:
        # Arrange
        factory = mocker.stub()

        # Act & Assert
        with pytest.raises(ValueError, match=r"^backend_name: Invalid value$"):
            AsyncBackendFactory.push_backend_factory(invalid_token, factory)

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____get_backend____returns_backend_instance_from_hook(
        self,
        backend_name: str,
    ) -> None:
        # Arrange
        expected_cls = self.BACKENDS[backend_name]

        # Act
        backend = AsyncBackendFactory.get_backend(backend_name)

        # Assert
        assert isinstance(backend, AsyncBackend)
        assert isinstance(backend, expected_cls)

    def test____get_backend____unknown_backend(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(NotImplementedError, match=r"^Unknown backend 'mock'$"):
            AsyncBackendFactory.get_backend("mock")

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____get_backend____by_default(self, backend_name: str) -> None:
        # Arrange
        AsyncBackendFactory.remove_installed_hooks()

        # Act & Assert
        match backend_name:
            case "asyncio":
                from easynetwork.lowlevel.std_asyncio import AsyncIOBackend

                assert type(AsyncBackendFactory.get_backend("asyncio")) is AsyncIOBackend
            case _:
                with pytest.raises(NotImplementedError, match=r"^Unknown backend '.+'$"):
                    AsyncBackendFactory.get_backend(backend_name)

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____get_backend____singleton(self, backend_name: str) -> None:
        # Arrange
        first_backend_instance = AsyncBackendFactory.get_backend(backend_name)

        # Act
        this_backend = AsyncBackendFactory.get_backend(backend_name)

        # Assert
        assert this_backend is first_backend_instance

    @pytest.mark.parametrize("action", ["push_backend_factory", "push_factory_hook"])
    def test____get_backend____add_hook(
        self,
        action: Literal["push_backend_factory", "push_factory_hook"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match action:
            case "push_backend_factory":
                AsyncBackendFactory.push_backend_factory("mock", lambda: MockBackend(mocker))
            case "push_factory_hook":

                def hook(name: str) -> AsyncBackend:
                    if name == "mock":
                        return MockBackend(mocker)
                    raise UnsupportedOperation

                AsyncBackendFactory.push_factory_hook(hook)
            case _:
                assert_never(action)

        # Act
        backend = AsyncBackendFactory.get_backend("mock")

        # Assert
        assert type(backend) is MockBackend

    @pytest.mark.parametrize("action", ["push_backend_factory", "push_factory_hook"])
    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____get_backend____override_backend(
        self,
        backend_name: str,
        action: Literal["push_backend_factory", "push_factory_hook"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match action:
            case "push_backend_factory":
                AsyncBackendFactory.push_backend_factory(backend_name, lambda: MockBackend(mocker))
            case "push_factory_hook":

                def hook(name: str) -> AsyncBackend:
                    if name == backend_name:
                        return MockBackend(mocker)
                    raise UnsupportedOperation

                AsyncBackendFactory.push_factory_hook(hook)
            case _:
                assert_never(action)

        # Act
        backend = AsyncBackendFactory.get_backend(backend_name)

        # Assert
        assert not isinstance(backend, self.BACKENDS[backend_name])
        assert isinstance(backend, MockBackend)

    @pytest.mark.parametrize("action", ["push_backend_factory", "push_factory_hook"])
    @pytest.mark.parametrize("invalid_cls", [int, Socket, TestAsyncBackend])
    def test____get_backend____error_do_not_derive_from_AsyncBackend(
        self,
        action: Literal["push_backend_factory", "push_factory_hook"],
        invalid_cls: type[Any],
    ) -> None:
        # Arrange
        match action:
            case "push_backend_factory":
                AsyncBackendFactory.push_backend_factory("mock", invalid_cls)
            case "push_factory_hook":

                def hook(name: str) -> AsyncBackend:
                    if name == "mock":
                        return invalid_cls()
                    raise UnsupportedOperation

                AsyncBackendFactory.push_factory_hook(hook)
            case _:
                assert_never(action)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^.+ did not return an AsyncBackend instance$"):
            AsyncBackendFactory.get_backend("mock")

    @pytest.mark.parametrize("action", ["push_backend_factory", "push_factory_hook"])
    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____get_backend____cache_erased_when_adding_new_hook(
        self,
        backend_name: str,
        action: Literal["push_backend_factory", "push_factory_hook"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        first_backend_instance = AsyncBackendFactory.get_backend(backend_name)

        # Act
        match action:
            case "push_backend_factory":
                AsyncBackendFactory.push_backend_factory(backend_name, lambda: MockBackend(mocker))
            case "push_factory_hook":

                def hook(name: str) -> AsyncBackend:
                    if name == backend_name:
                        return MockBackend(mocker)
                    raise UnsupportedOperation

                AsyncBackendFactory.push_factory_hook(hook)
            case _:
                assert_never(action)
        this_backend = AsyncBackendFactory.get_backend(backend_name)

        # Assert
        assert this_backend is not first_backend_instance

    def test____get_backend____cache_erased_when_removing_installed_hook(self) -> None:
        # Arrange
        first_backend_instance = AsyncBackendFactory.get_backend("asyncio")
        assert isinstance(first_backend_instance, FakeAsyncIOBackend)

        from easynetwork.lowlevel.std_asyncio import AsyncIOBackend as OriginalAsyncIOBackend

        # Act
        AsyncBackendFactory.remove_installed_hooks()
        this_backend = AsyncBackendFactory.get_backend("asyncio")

        # Assert
        assert isinstance(this_backend, OriginalAsyncIOBackend)

    def test____get_backend____cache_not_erased_if_there_was_no_hook(self) -> None:
        # Arrange
        AsyncBackendFactory.remove_installed_hooks()

        from easynetwork.lowlevel.std_asyncio import AsyncIOBackend as OriginalAsyncIOBackend

        first_backend_instance = AsyncBackendFactory.get_backend("asyncio")
        assert isinstance(first_backend_instance, OriginalAsyncIOBackend)

        # Act
        AsyncBackendFactory.remove_installed_hooks()
        this_backend = AsyncBackendFactory.get_backend("asyncio")

        # Assert
        assert this_backend is first_backend_instance

    @pytest.mark.parametrize("running_backend_name", list(BACKENDS))
    def test____current____returns_running_backend(
        self,
        running_backend_name: str,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_cls = self.BACKENDS[running_backend_name]

        mock_current_async_library: MagicMock = mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value=running_backend_name,
        )

        # Act
        backend = AsyncBackendFactory.current()

        # Assert
        mock_current_async_library.assert_called_once_with()
        assert isinstance(backend, expected_cls)

    def test____current____running_library_does_not_have_backend_implementation(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_current_async_library: MagicMock = mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value="some_other_async_runner",
        )

        # Act & Assert
        with pytest.raises(
            NotImplementedError,
            match=r"^Running library 'some_other_async_runner' misses the backend implementation$",
        ):
            AsyncBackendFactory.current()

        # Assert
        mock_current_async_library.assert_called_once_with()

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____current____by_default(self, backend_name: str, mocker: MockerFixture) -> None:
        # Arrange
        AsyncBackendFactory.remove_installed_hooks()
        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value=backend_name,
        )

        # Act & Assert
        match backend_name:
            case "asyncio":
                from easynetwork.lowlevel.std_asyncio import AsyncIOBackend

                assert type(AsyncBackendFactory.current()) is AsyncIOBackend
            case _:
                with pytest.raises(NotImplementedError, match=r"^Running library '.+' misses the backend implementation$"):
                    AsyncBackendFactory.current()

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____current____singleton(self, backend_name: str, mocker: MockerFixture) -> None:
        # Arrange
        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value=backend_name,
        )
        first_backend_instance = AsyncBackendFactory.current()

        # Act
        this_backend = AsyncBackendFactory.current()

        # Assert
        assert this_backend is first_backend_instance

    @pytest.mark.parametrize("action", ["push_backend_factory", "push_factory_hook"])
    def test____current____add_hook(
        self,
        action: Literal["push_backend_factory", "push_factory_hook"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match action:
            case "push_backend_factory":
                AsyncBackendFactory.push_backend_factory("mock", lambda: MockBackend(mocker))
            case "push_factory_hook":

                def hook(name: str) -> AsyncBackend:
                    if name == "mock":
                        return MockBackend(mocker)
                    raise UnsupportedOperation

                AsyncBackendFactory.push_factory_hook(hook)
            case _:
                assert_never(action)

        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value="mock",
        )

        # Act
        backend = AsyncBackendFactory.current()

        # Assert
        assert type(backend) is MockBackend

    @pytest.mark.parametrize("action", ["push_backend_factory", "push_factory_hook"])
    @pytest.mark.parametrize("invalid_cls", [int, Socket, TestAsyncBackend])
    def test____current____error_do_not_derive_from_AsyncBackend(
        self,
        action: Literal["push_backend_factory", "push_factory_hook"],
        invalid_cls: type[Any],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match action:
            case "push_backend_factory":
                AsyncBackendFactory.push_backend_factory("mock", invalid_cls)
            case "push_factory_hook":

                def hook(name: str) -> AsyncBackend:
                    if name == "mock":
                        return invalid_cls()
                    raise UnsupportedOperation

                AsyncBackendFactory.push_factory_hook(hook)
            case _:
                assert_never(action)

        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value="mock",
        )

        # Act & Assert
        with pytest.raises(TypeError, match=r"^.+ did not return an AsyncBackend instance$"):
            AsyncBackendFactory.current()

    @pytest.mark.parametrize("action", ["push_backend_factory", "push_factory_hook"])
    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____current____override_backend(
        self,
        backend_name: str,
        action: Literal["push_backend_factory", "push_factory_hook"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        match action:
            case "push_backend_factory":
                AsyncBackendFactory.push_backend_factory(backend_name, lambda: MockBackend(mocker))
            case "push_factory_hook":

                def hook(name: str) -> AsyncBackend:
                    if name == backend_name:
                        return MockBackend(mocker)
                    raise UnsupportedOperation

                AsyncBackendFactory.push_factory_hook(hook)
            case _:
                assert_never(action)

        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value=backend_name,
        )

        # Act
        backend = AsyncBackendFactory.current()

        # Assert
        assert not isinstance(backend, self.BACKENDS[backend_name])
        assert isinstance(backend, MockBackend)

    @pytest.mark.parametrize("action", ["push_backend_factory", "push_factory_hook"])
    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____current____cache_erased_when_adding_new_hook(
        self,
        backend_name: str,
        action: Literal["push_backend_factory", "push_factory_hook"],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value=backend_name,
        )
        first_backend_instance = AsyncBackendFactory.current()

        match action:
            case "push_backend_factory":
                AsyncBackendFactory.push_backend_factory(backend_name, lambda: MockBackend(mocker))
            case "push_factory_hook":

                def hook(name: str) -> AsyncBackend:
                    if name == backend_name:
                        return MockBackend(mocker)
                    raise UnsupportedOperation

                AsyncBackendFactory.push_factory_hook(hook)
            case _:
                assert_never(action)

        # Act
        this_backend = AsyncBackendFactory.current()

        # Assert
        assert this_backend is not first_backend_instance

    def test____current____cache_erased_when_removing_installed_hook(self, mocker: MockerFixture) -> None:
        # Arrange
        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value="asyncio",
        )
        first_backend_instance = AsyncBackendFactory.current()
        assert isinstance(first_backend_instance, FakeAsyncIOBackend)

        from easynetwork.lowlevel.std_asyncio import AsyncIOBackend as OriginalAsyncIOBackend

        # Act
        AsyncBackendFactory.remove_installed_hooks()
        this_backend = AsyncBackendFactory.current()

        # Assert
        assert isinstance(this_backend, OriginalAsyncIOBackend)

    def test____current____cache_not_erased_if_there_was_no_hook(self, mocker: MockerFixture) -> None:
        # Arrange
        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value="asyncio",
        )
        AsyncBackendFactory.remove_installed_hooks()

        from easynetwork.lowlevel.std_asyncio import AsyncIOBackend as OriginalAsyncIOBackend

        first_backend_instance = AsyncBackendFactory.current()
        assert isinstance(first_backend_instance, OriginalAsyncIOBackend)

        # Act
        AsyncBackendFactory.remove_installed_hooks()
        this_backend = AsyncBackendFactory.current()

        # Assert
        assert this_backend is first_backend_instance
