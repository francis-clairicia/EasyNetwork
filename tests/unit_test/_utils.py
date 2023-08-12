from __future__ import annotations

import functools
from collections.abc import Sequence
from socket import AF_INET, AF_INET6, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM
from types import TracebackType
from typing import Any

_DEFAULT_FAMILIES: Sequence[int] = (AF_INET, AF_INET6)


class _LockMixin:
    _locked_count: int = 0

    class WouldBlock(Exception):
        pass

    def _acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if self._locked_count > 0:
            if not blocking or timeout >= 0:
                return False
            raise _LockMixin.WouldBlock(f"{self.__class__.__name__}.acquire() would block")

        self._locked_count += 1
        return True

    def locked(self) -> bool:
        return self._locked_count > 0

    def _release(self) -> None:
        assert self._locked_count > 0
        self._locked_count -= 1


class DummyLock(_LockMixin):
    """
    Helper class used to mock threading.Lock and threading.RLock classes
    """

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.release()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        return self._acquire(blocking=blocking, timeout=timeout)

    def release(self) -> None:
        return self._release()


class AsyncDummyLock(_LockMixin):
    """
    Helper class used to mock asyncio.Lock classes
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


def get_all_socket_families() -> frozenset[str]:
    return _get_all_socket_families()


@functools.cache
def _get_all_socket_families() -> frozenset[str]:
    import socket

    return frozenset(v for v in dir(socket) if v.startswith("AF_"))


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
