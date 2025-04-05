from __future__ import annotations

import contextlib
import functools
import inspect
import threading
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Iterator, Sequence
from socket import AF_INET, AF_INET6, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM
from types import TracebackType
from typing import TYPE_CHECKING, Any

import pytest

from ..fixtures.socket import ALL_SOCKET_FAMILIES

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture

_DEFAULT_FAMILIES: Sequence[int] = (AF_INET6, AF_INET)


class _LockMixin:
    _owner: object = None
    _locked_count: int = 0
    _reentrant: bool = False

    class WouldBlock(Exception):
        pass

    def _get_requester_id(self) -> object:
        raise NotImplementedError

    def _acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if self._locked_count > 0 and (not self._reentrant or self._owner != self._get_requester_id()):
            if not blocking or timeout >= 0:
                return False
            raise _LockMixin.WouldBlock(f"{self.__class__.__name__}.acquire() would block")

        if self._reentrant and self._owner is None:
            self._owner = self._get_requester_id()
        self._locked_count += 1
        return True

    def locked(self) -> bool:
        return self._locked_count > 0

    def _release(self) -> None:
        if self._reentrant and self._owner != self._get_requester_id():
            raise RuntimeError("release() called on an unacquired lock")
        assert self._locked_count > 0
        self._locked_count -= 1
        if self._reentrant and self._locked_count == 0:
            self._owner = None


class DummyLock(_LockMixin):
    """
    Helper class used to mock threading.Lock class.
    """

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.release()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        return self._acquire(blocking=blocking, timeout=timeout)

    def release(self) -> None:
        return self._release()


class DummyRLock(DummyLock):
    """
    Helper class used to mock threading.RLock class.
    """

    _reentrant = True

    def _get_requester_id(self) -> object:
        return threading.get_ident()


class AsyncDummyLock(_LockMixin):
    """
    Helper class used to mock asyncio.Lock class.
    """

    class AcquireFailed(Exception):
        pass

    async def __aenter__(self) -> None:
        await self.acquire()

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        self.release()

    async def acquire(self) -> bool:
        locked = self._acquire(blocking=False)
        if not locked:
            raise AsyncDummyLock.AcquireFailed("not locked")
        return True

    def release(self) -> None:
        return self._release()


class partial_eq(functools.partial[Any]):
    """Helper to check equality with two functools.partial() object

    (c.f. https://github.com/python/cpython/issues/47814)
    """

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, functools.partial):
            return NotImplemented
        return self.func == other.func and self.args == other.args and self.keywords == other.keywords


def unsupported_families(supported_families: Iterable[str]) -> tuple[str, ...]:
    if isinstance(supported_families, str):
        raise ValueError("does not expect a str directly")
    return tuple(sorted(ALL_SOCKET_FAMILIES.difference(supported_families)))


def __addrinfo_list(
    port: int,
    socktype: int,
    proto: int,
    families: Sequence[int],
) -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    assert families, "families is empty"

    infos: list[tuple[int, int, int, str, tuple[Any, ...]]] = []

    for af in families:
        sockaddr: tuple[Any, ...]
        if af == AF_INET:
            sockaddr = ("127.0.0.1", port)
        elif af == AF_INET6:
            sockaddr = ("::1", port, 0, 0)
        else:
            raise ValueError(af)
        infos.append((af, socktype, proto, "", sockaddr))
    return infos


def stream_addrinfo_list(
    port: int,
    families: Sequence[int] = _DEFAULT_FAMILIES,
) -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    return __addrinfo_list(port, SOCK_STREAM, IPPROTO_TCP, families)


def datagram_addrinfo_list(
    port: int,
    families: Sequence[int] = _DEFAULT_FAMILIES,
) -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    return __addrinfo_list(port, SOCK_DGRAM, IPPROTO_UDP, families)


_original_import_module = __import__


def mock_import_module_not_found(modules: set[str] | frozenset[str], mocker: MockerFixture) -> MagicMock:
    modules = frozenset(modules)

    def mock_import_side_effect(name: str, *args: Any) -> Any:
        if name in modules:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return _original_import_module(name, *args)

    mock_import: MagicMock = mocker.patch("builtins.__import__")
    mock_import.side_effect = mock_import_side_effect
    return mock_import


def __make_write_in_buffer_side_effect(to_write: bytes | list[bytes]) -> Callable[[bytearray | memoryview], int]:
    def write_in_buffer(buffer: memoryview, to_write: bytes) -> int:
        nbytes = len(to_write)
        buffer[:nbytes] = to_write
        return nbytes

    match to_write:
        case bytes():

            def write_in_buffer_side_effect(buffer: bytearray | memoryview) -> int:
                with memoryview(buffer) as buffer:
                    return write_in_buffer(buffer, to_write)

        case list() if all(isinstance(b, bytes) for b in to_write):
            iterator = iter(to_write)

            def write_in_buffer_side_effect(buffer: bytearray | memoryview) -> int:
                with memoryview(buffer) as buffer:
                    return write_in_buffer(buffer, next(iterator))

        case _:
            pytest.fail("Invalid setup")

    return write_in_buffer_side_effect


def make_recv_into_side_effect(to_write: bytes | list[bytes]) -> Callable[[bytearray | memoryview, float], int]:
    write_in_buffer = __make_write_in_buffer_side_effect(to_write)

    def recv_into_side_effect(buffer: bytearray | memoryview, timeout: float) -> int:
        return write_in_buffer(buffer)

    return recv_into_side_effect


def make_recv_noblock_into_side_effect(to_write: bytes | list[bytes]) -> Callable[[bytearray | memoryview], int]:
    write_in_buffer = __make_write_in_buffer_side_effect(to_write)

    def recv_into_side_effect(buffer: bytearray | memoryview) -> int:
        return write_in_buffer(buffer)

    return recv_into_side_effect


def make_async_recv_into_side_effect(to_write: bytes | list[bytes]) -> Callable[[bytearray | memoryview], Awaitable[int]]:
    write_in_buffer = __make_write_in_buffer_side_effect(to_write)

    async def recv_into_side_effect(buffer: bytearray | memoryview) -> int:
        return write_in_buffer(buffer)

    return recv_into_side_effect


def stub_decorator(mocker: MockerFixture, name: str | None = None) -> Callable[[Callable[..., Any]], MagicMock]:

    def decorator(f: Callable[..., Any]) -> MagicMock:
        stub = mocker.stub(name)
        stub.side_effect = f
        return stub

    return decorator


def async_stub_decorator(
    mocker: MockerFixture,
    name: str | None = None,
) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], AsyncMock]:

    def decorator(f: Callable[..., Coroutine[Any, Any, Any]]) -> AsyncMock:
        if not inspect.iscoroutinefunction(f):
            raise TypeError("decorated function must be a coroutine function")
        stub = mocker.async_stub(name)
        stub.side_effect = f
        return stub

    return decorator


@contextlib.contextmanager
def restore_mock_side_effect(mock: MagicMock) -> Iterator[None]:
    default_side_effect = mock.side_effect
    default_return_value = mock.side_effect
    try:
        yield
    finally:
        mock.side_effect = default_side_effect
        mock.return_value = default_return_value


@contextlib.contextmanager
def temporary_mock_side_effect(mock: MagicMock, side_effect: Any) -> Iterator[None]:
    with restore_mock_side_effect(mock):
        mock.side_effect = side_effect
        yield
