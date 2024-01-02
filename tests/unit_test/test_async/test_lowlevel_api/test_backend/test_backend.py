from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterator
from socket import socket as Socket
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, final

from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend, TaskInfo
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

    async def ignore_cancellation(self, coroutine: Awaitable[Any]) -> Any:
        return await coroutine


class TestTaskInfo:
    def test____equality____between_two_task_info_objects____equal(self, mocker: MockerFixture) -> None:
        # Arrange
        t1 = TaskInfo(123456, "task", mocker.sentinel.coro)
        t2 = TaskInfo(123456, "task", mocker.sentinel.coro)

        # Act & Assert
        assert t1 == t2

    def test____equality____between_two_task_info_objects____not_equal(self, mocker: MockerFixture) -> None:
        # Arrange
        t1 = TaskInfo(123456, "task", mocker.sentinel.coro)
        t2 = TaskInfo(789123, "task", mocker.sentinel.coro)

        # Act & Assert
        assert t1 != t2

    def test____equality____with_other_object____not_implemented(self, mocker: MockerFixture) -> None:
        # Arrange
        t1 = TaskInfo(123456, "task", mocker.sentinel.coro)
        t2 = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        assert t1 != t2

    def test____hash___from_id(self, mocker: MockerFixture) -> None:
        # Arrange
        t = TaskInfo(123456, "task", mocker.sentinel.coro)

        # Act & Assert
        assert hash(t) == hash(t.id)


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

    FACTORY_HOOKS = MappingProxyType({k: AsyncBackendFactory.backend_factory_hook(k, v) for k, v in BACKENDS.items()})

    CURRENT_ASYNC_LIBRARY_FUNC: str = "easynetwork.lowlevel.api_async.backend._sniffio_helpers.current_async_library"

    @pytest.fixture(autouse=True)
    def setup_factory(self, mocker: MockerFixture) -> Iterator[None]:
        _real_push_factory = AsyncBackendFactory.push_factory_hook

        with contextlib.ExitStack() as registered_hook_flush_stack:
            self.registered_hook_flush_stack = registered_hook_flush_stack

            def push_factory_hook(factory: Callable[[str], AsyncBackend | None]) -> None:
                _real_push_factory(factory)
                registered_hook_flush_stack.callback(AsyncBackendFactory.remove_factory_hook, factory)

            self._act__add_hook = push_factory_hook

            mocker.patch.object(AsyncBackendFactory, "push_factory_hook", side_effect=AssertionError("Use self._act__add_hook()"))

            for hook in self.FACTORY_HOOKS.values():
                self._act__add_hook(hook)
                del hook

            yield

    def test____push_factory_hook____not_callable(self, mocker: MockerFixture) -> None:
        # Arrange
        obj = mocker.NonCallableMock()

        # Act & Assert
        with pytest.raises(TypeError, match=r"^.+ is not callable$"):
            self._act__add_hook(obj)

    def test____push_factory_hook____registered_twice(self, mocker: MockerFixture) -> None:
        # Arrange
        hook = mocker.stub()
        self._act__add_hook(hook)

        # Act & Assert
        with pytest.raises(ValueError, match=r"^.+ is already registered$"):
            self._act__add_hook(hook)

    def test____backend_factory_hook____not_callable(self, mocker: MockerFixture) -> None:
        # Arrange
        obj = mocker.NonCallableMock()

        # Act & Assert
        with pytest.raises(TypeError, match=r"^.+ is not callable$"):
            _ = AsyncBackendFactory.backend_factory_hook("mock", obj)

    def test____backend_factory_hook____backend_is_not_a_string(self, mocker: MockerFixture) -> None:
        # Arrange
        factory = mocker.stub()

        # Act & Assert
        with pytest.raises(TypeError, match=r"^backend_name: Expected a string$"):
            _ = AsyncBackendFactory.backend_factory_hook(4, factory)  # type: ignore[arg-type]

    @pytest.mark.parametrize("invalid_token", ["", "   ", "\nasyncio", "asyncio\t"], ids=repr)
    def test____backend_factory_hook____backend_string_is_invalid(self, invalid_token: str, mocker: MockerFixture) -> None:
        # Arrange
        factory = mocker.stub()

        # Act & Assert
        with pytest.raises(ValueError, match=r"^backend_name: Invalid value$"):
            _ = AsyncBackendFactory.backend_factory_hook(invalid_token, factory)

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
        self.registered_hook_flush_stack.close()

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

    def test____get_backend____add_hook(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def hook(name: str) -> AsyncBackend | None:
            if name == "mock":
                return MockBackend(mocker)
            return None

        self._act__add_hook(hook)

        # Act
        backend = AsyncBackendFactory.get_backend("mock")

        # Assert
        assert type(backend) is MockBackend

    def test____get_backend____remove_hook(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def hook(name: str) -> AsyncBackend | None:
            if name == "mock":
                return MockBackend(mocker)
            return None

        self._act__add_hook(hook)
        _ = AsyncBackendFactory.get_backend("mock")

        # Act
        AsyncBackendFactory.remove_factory_hook(hook)

        # Assert
        with pytest.raises(NotImplementedError, match=r"^Unknown backend 'mock'$"):
            AsyncBackendFactory.get_backend("mock")

    def test____get_backend____remove_unknown_hook(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def hook(name: str) -> AsyncBackend | None:
            if name == "mock":
                return MockBackend(mocker)
            return None

        backend = AsyncBackendFactory.get_backend("asyncio")

        # Act & Assert
        AsyncBackendFactory.remove_factory_hook(hook)
        assert AsyncBackendFactory.get_backend("asyncio") is backend

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____get_backend____override_backend(
        self,
        backend_name: str,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def hook(name: str) -> AsyncBackend | None:
            if name == backend_name:
                return MockBackend(mocker)
            return None

        self._act__add_hook(hook)

        # Act
        backend = AsyncBackendFactory.get_backend(backend_name)

        # Assert
        assert not isinstance(backend, self.BACKENDS[backend_name])
        assert isinstance(backend, MockBackend)

    @pytest.mark.parametrize("invalid_cls", [int, Socket, TestAsyncBackend])
    @pytest.mark.parametrize("using_backend_factory", [False, True], ids=lambda p: f"using_backend_factory=={p}")
    def test____get_backend____error_do_not_derive_from_AsyncBackend(
        self,
        invalid_cls: type[Any],
        using_backend_factory: bool,
    ) -> None:
        # Arrange
        if using_backend_factory:
            hook = AsyncBackendFactory.backend_factory_hook("mock", invalid_cls)
        else:

            def hook(name: str) -> AsyncBackend | None:
                if name == "mock":
                    return invalid_cls()
                return None

        self._act__add_hook(hook)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^.+ did not return an AsyncBackend instance$"):
            AsyncBackendFactory.get_backend("mock")

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____get_backend____cache_erased_when_adding_new_hook(
        self,
        backend_name: str,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        first_backend_instance = AsyncBackendFactory.get_backend(backend_name)

        # Act
        def hook(name: str) -> AsyncBackend | None:
            if name == backend_name:
                return MockBackend(mocker)
            return None

        self._act__add_hook(hook)
        this_backend = AsyncBackendFactory.get_backend(backend_name)

        # Assert
        assert this_backend is not first_backend_instance

    def test____get_backend____cache_erased_when_removing_installed_hook(self) -> None:
        # Arrange
        first_backend_instance = AsyncBackendFactory.get_backend("asyncio")
        assert isinstance(first_backend_instance, FakeAsyncIOBackend)

        from easynetwork.lowlevel.std_asyncio import AsyncIOBackend as OriginalAsyncIOBackend

        # Act
        AsyncBackendFactory.remove_factory_hook(self.FACTORY_HOOKS["asyncio"])
        this_backend = AsyncBackendFactory.get_backend("asyncio")

        # Assert
        assert isinstance(this_backend, OriginalAsyncIOBackend)

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
        self.registered_hook_flush_stack.close()
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

    def test____current____add_hook(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def hook(name: str) -> AsyncBackend | None:
            if name == "mock":
                return MockBackend(mocker)
            return None

        self._act__add_hook(hook)

        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value="mock",
        )

        # Act
        backend = AsyncBackendFactory.current()

        # Assert
        assert type(backend) is MockBackend

    @pytest.mark.parametrize("invalid_cls", [int, Socket, TestAsyncBackend])
    @pytest.mark.parametrize("using_backend_factory", [False, True], ids=lambda p: f"using_backend_factory=={p}")
    def test____current____error_do_not_derive_from_AsyncBackend(
        self,
        invalid_cls: type[Any],
        using_backend_factory: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if using_backend_factory:
            hook = AsyncBackendFactory.backend_factory_hook("mock", invalid_cls)
        else:

            def hook(name: str) -> AsyncBackend | None:
                if name == "mock":
                    return invalid_cls()
                return None

        self._act__add_hook(hook)

        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value="mock",
        )

        # Act & Assert
        with pytest.raises(TypeError, match=r"^.+ did not return an AsyncBackend instance$"):
            AsyncBackendFactory.current()

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____current____override_backend(
        self,
        backend_name: str,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        def hook(name: str) -> AsyncBackend | None:
            if name == backend_name:
                return MockBackend(mocker)
            return None

        self._act__add_hook(hook)

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

    @pytest.mark.parametrize("backend_name", list(BACKENDS))
    def test____current____cache_erased_when_adding_new_hook(
        self,
        backend_name: str,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mocker.patch(
            self.CURRENT_ASYNC_LIBRARY_FUNC,
            autospec=True,
            return_value=backend_name,
        )
        first_backend_instance = AsyncBackendFactory.current()

        # Act
        def hook(name: str) -> AsyncBackend | None:
            if name == backend_name:
                return MockBackend(mocker)
            return None

        self._act__add_hook(hook)
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
        AsyncBackendFactory.remove_factory_hook(self.FACTORY_HOOKS["asyncio"])
        this_backend = AsyncBackendFactory.current()

        # Assert
        assert isinstance(this_backend, OriginalAsyncIOBackend)
