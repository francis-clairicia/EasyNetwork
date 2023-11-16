# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
from __future__ import annotations

__all__ = [
    "ElapsedTime",
    "check_real_socket_state",
    "check_socket_family",
    "check_socket_no_ssl",
    "ensure_datagram_socket_bound",
    "error_from_errno",
    "exception_with_notes",
    "is_ssl_eof_error",
    "is_ssl_socket",
    "lock_with_timeout",
    "make_callback",
    "prepend_argument",
    "remove_traceback_frames_in_place",
    "replace_kwargs",
    "set_reuseport",
    "validate_timeout_delay",
]

import contextlib
import errno as _errno
import functools
import math
import os
import socket as _socket
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, Self, TypeGuard, TypeVar

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    ssl = None
else:
    ssl = _ssl
    del _ssl

from . import constants
from .socket import AddressFamily

if TYPE_CHECKING:
    from ssl import SSLError as _SSLError, SSLSocket as _SSLSocket

    from .socket import ISocket, SupportsSocketOptions

_P = ParamSpec("_P")
_R = TypeVar("_R")
_T_Arg = TypeVar("_T_Arg")

_ExcType = TypeVar("_ExcType", bound=BaseException)
_FuncType = TypeVar("_FuncType", bound=Callable[..., Any])


def replace_kwargs(kwargs: dict[str, Any], keys: dict[str, str]) -> None:
    if not keys:
        raise ValueError("Empty key dict")
    for old_key, new_key in keys.items():
        if new_key in kwargs:
            raise TypeError(f"Cannot set {old_key!r} to {new_key!r}: {new_key!r} in dictionary")
        try:
            kwargs[new_key] = kwargs.pop(old_key)
        except KeyError:
            pass


def make_callback(func: Callable[_P, _R], /, *args: _P.args, **kwargs: _P.kwargs) -> Callable[[], _R]:
    return functools.partial(func, *args, **kwargs)


def prepend_argument(arg: _T_Arg) -> Callable[[Callable[Concatenate[_T_Arg, _P], _R]], Callable[_P, _R]]:
    def decorator(func: Callable[Concatenate[_T_Arg, _P], _R], /) -> Callable[_P, _R]:
        return functools.partial(func, arg)

    return decorator


def inherit_doc(base_cls: type[Any]) -> Callable[[_FuncType], _FuncType]:
    assert isinstance(base_cls, type)  # nosec assert_used

    def decorator(dest_func: _FuncType) -> _FuncType:
        ref_func: Any = getattr(base_cls, dest_func.__name__)
        dest_func.__doc__ = ref_func.__doc__
        return dest_func

    return decorator


def error_from_errno(errno: int) -> OSError:
    return OSError(errno, os.strerror(errno))


def check_socket_family(family: int) -> None:
    supported_families = AddressFamily.__members__

    if family not in supported_families.values():
        raise ValueError(f"Only these families are supported: {', '.join(supported_families)}")


def check_real_socket_state(socket: ISocket) -> None:
    """Verify socket saved error and raise OSError if there is one

    There is some functions such as socket.send() which do not immediately fail and save the errno
    in SO_ERROR socket option because the error spawn after the action was sent to the kernel (Something weird)

    On Windows: The returned value should be the error returned by WSAGetLastError(), but the socket methods always call
    this function to raise an error, so getsockopt(SO_ERROR) will most likely always return zero :)
    """
    if socket.fileno() < 0:
        return
    errno = socket.getsockopt(_socket.SOL_SOCKET, _socket.SO_ERROR)
    if errno != 0:
        # The SO_ERROR is automatically reset to zero after getting the value
        raise error_from_errno(errno)


def is_ssl_socket(socket: _socket.socket) -> TypeGuard[_SSLSocket]:
    if ssl is None:
        return False
    return isinstance(socket, ssl.SSLSocket)


def check_socket_no_ssl(socket: _socket.socket) -> None:
    if is_ssl_socket(socket):
        raise TypeError("ssl.SSLSocket instances are forbidden")


def validate_timeout_delay(delay: float, *, positive_check: bool) -> float:
    if math.isnan(delay):
        raise ValueError("Invalid delay: NaN (not a number)")
    if positive_check and delay < 0:
        raise ValueError("Invalid delay: negative value")
    return delay


def is_ssl_eof_error(exc: BaseException) -> TypeGuard[_SSLError]:
    if ssl is None:
        return False

    match exc:
        case ssl.SSLEOFError():
            return True
        case ssl.SSLError() if hasattr(exc, "strerror") and "UNEXPECTED_EOF_WHILE_READING" in exc.strerror:
            # From Trio project:
            # There appears to be a bug on Python 3.10, where SSLErrors
            # aren't properly translated into SSLEOFErrors.
            # This stringly-typed error check is borrowed from the AnyIO
            # project.
            return True
    return False


def iter_bytes(b: bytes | bytearray | memoryview) -> Iterator[bytes]:
    return map(int.to_bytes, b)


def is_socket_connected(sock: ISocket) -> bool:
    try:
        sock.getpeername()
    except OSError as exc:
        if exc.errno not in constants.NOT_CONNECTED_SOCKET_ERRNOS:
            raise
        connected = False
    else:
        connected = True
    return connected


def check_socket_is_connected(sock: ISocket) -> None:
    if not is_socket_connected(sock):
        raise error_from_errno(_errno.ENOTCONN)


def ensure_datagram_socket_bound(sock: _socket.socket) -> None:
    check_socket_family(sock.family)
    if sock.type != _socket.SOCK_DGRAM:
        raise ValueError("A 'SOCK_DGRAM' socket is expected")
    try:
        is_bound: bool = sock.getsockname()[1] > 0
    except OSError as exc:
        if exc.errno != _errno.EINVAL:
            raise
        is_bound = False

    if not is_bound:
        sock.bind(("localhost", 0))


def set_reuseport(sock: SupportsSocketOptions) -> None:
    if not hasattr(_socket, "SO_REUSEPORT"):
        raise ValueError("reuse_port not supported by socket module")
    else:
        try:
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, True)
        except OSError:
            raise ValueError("reuse_port not supported by socket module, SO_REUSEPORT defined but not implemented.") from None


def exception_with_notes(exc: _ExcType, notes: str | Iterable[str]) -> _ExcType:
    if isinstance(notes, str):
        notes = (notes,)
    for note in notes:
        exc.add_note(note)
    return exc


def remove_traceback_frames_in_place(exc: _ExcType, n: int) -> _ExcType:
    tb = exc.__traceback__
    for _ in range(n):
        if tb is None:
            break
        tb = tb.tb_next
    return exc.with_traceback(tb)


class ElapsedTime:
    __slots__ = ("_current_time_func", "_start_time", "_end_time")

    def __init__(self) -> None:
        self._current_time_func: Callable[[], float] = time.perf_counter
        self._start_time: float | None = None
        self._end_time: float | None = None

    def __enter__(self) -> Self:
        if self._start_time is not None:
            raise RuntimeError("Already entered")
        self._start_time = self._current_time_func()
        return self

    def __exit__(self, *args: Any) -> None:
        end_time = self._current_time_func()
        if self._end_time is not None:
            raise RuntimeError("Already exited")
        self._end_time = end_time

    def get_elapsed(self) -> float:
        start_time = self._start_time
        if start_time is None:
            raise RuntimeError("Not entered")
        end_time = self._end_time
        if end_time is None:
            raise RuntimeError("Within context")
        return end_time - start_time

    def recompute_timeout(self, old_timeout: float) -> float:
        elapsed_time = self.get_elapsed()
        new_timeout = old_timeout - elapsed_time
        if new_timeout < 0.0:
            new_timeout = 0.0
        return new_timeout


@contextlib.contextmanager
def lock_with_timeout(
    lock: threading.RLock | threading.Lock,
    timeout: float | None,
) -> Iterator[float | None]:
    if timeout is None or timeout == math.inf:
        with lock:
            yield timeout
        return
    timeout = validate_timeout_delay(timeout, positive_check=True)
    with contextlib.ExitStack() as stack:
        # Try to acquire without blocking first
        if lock.acquire(blocking=False):
            stack.push(lock)
        else:
            with ElapsedTime() as elapsed:
                if timeout == 0 or not lock.acquire(True, timeout):
                    raise error_from_errno(_errno.ETIMEDOUT)
            stack.push(lock)
            timeout = elapsed.recompute_timeout(timeout)
        yield timeout


class ResourceGuard:
    __slots__ = (
        "__semaphore",
        "__msg",
        "__held",
    )

    def __init__(self, message: str) -> None:
        # A semaphore is used to check consistency between __enter__ and __exit__ calls (misnesting contexts)
        self.__semaphore = threading.BoundedSemaphore(value=1)
        self.__msg = message

    def __enter__(self) -> None:
        if not self.__semaphore.acquire(blocking=False):
            from ..exceptions import BusyResourceError

            msg = self.__msg
            raise BusyResourceError(msg)

    def __exit__(self, *args: Any) -> None:
        self.__semaphore.release()
