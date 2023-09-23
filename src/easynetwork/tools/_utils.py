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
    "remove_traceback_frames_in_place",
    "replace_kwargs",
    "retry_socket_method",
    "retry_ssl_socket_method",
    "set_reuseport",
    "validate_timeout_delay",
    "wait_socket_available",
]

import contextlib
import errno as _errno
import functools
import os
import selectors as _selectors
import socket as _socket
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from math import isinf, isnan
from typing import TYPE_CHECKING, Any, Literal, ParamSpec, TypeGuard, TypeVar, assert_never

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    ssl = None
else:
    ssl = _ssl
    del _ssl

from .socket import AddressFamily

if TYPE_CHECKING:
    from ssl import SSLError as _SSLError, SSLSocket as _SSLSocket

    from .socket import ISocket, SupportsSocketOptions

_P = ParamSpec("_P")
_R = TypeVar("_R")

_ExcType = TypeVar("_ExcType", bound=BaseException)


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


def wait_socket_available(socket: _socket.socket, timeout: float | None, event: Literal["read", "write"]) -> bool:
    try:
        selector_cls: type[_selectors.BaseSelector] = getattr(_selectors, "PollSelector")
    except AttributeError:
        selector_cls = _selectors.SelectSelector

    with selector_cls() as selector:
        try:
            match event:
                case "read":
                    selector.register(socket, _selectors.EVENT_READ)
                case "write":
                    selector.register(socket, _selectors.EVENT_WRITE)
                case _:  # pragma: no cover
                    assert_never(event)
            ready_list = selector.select(timeout)
        except (OSError, ValueError):
            # There will be a OSError when using this socket afterward.
            return True
        return bool(ready_list)


class _WouldBlock(Exception):
    def __init__(self, event: Literal["read", "write"]) -> None:
        super().__init__(event)
        self.event: Literal["read", "write"] = event


def _retry_impl(
    socket: _socket.socket,
    timeout: float | None,
    retry_interval: float | None,
    callback: Callable[[], _R],
) -> _R:
    assert socket.gettimeout() == 0, "The socket must be non-blocking"  # nosec assert_used

    perf_counter = time.perf_counter  # pull function to local namespace
    event: Literal["read", "write"]
    if timeout is not None:
        timeout = validate_timeout_delay(timeout, positive_check=False)
        if isinf(timeout) and timeout > 0:
            timeout = None
    if retry_interval is not None:
        retry_interval = validate_timeout_delay(retry_interval, positive_check=True)
        if isinf(retry_interval):
            retry_interval = None
    while True:
        try:
            return callback()
        except _WouldBlock as exc:
            event = exc.event
        if timeout is not None and timeout <= 0:
            break
        is_retry_interval: bool
        wait_time: float | None
        if retry_interval is None or (timeout is not None and timeout <= retry_interval):
            is_retry_interval = False
            wait_time = timeout
        else:
            is_retry_interval = True
            wait_time = retry_interval
        _start = perf_counter()
        if not wait_socket_available(socket, wait_time, event):
            if not is_retry_interval:
                break
        _end = perf_counter()
        if timeout is not None:
            timeout -= _end - _start
    if timeout is None:  # pragma: no cover
        raise RuntimeError("timeout error with timeout=None ?")
    raise error_from_errno(_errno.ETIMEDOUT)


def validate_timeout_delay(delay: float, *, positive_check: bool) -> float:
    if isnan(delay):
        raise ValueError("Invalid delay: NaN (not a number)")
    if positive_check and delay < 0:
        raise ValueError("Invalid delay: negative value")
    return delay


def retry_socket_method(
    socket: _socket.socket,
    timeout: float | None,
    retry_interval: float | None,
    event: Literal["read", "write"],
    socket_method: Callable[_P, _R],
    /,
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _R:
    assert not is_ssl_socket(socket), "ssl.SSLSocket instances are forbidden"  # nosec assert_used

    def callback() -> _R:
        try:
            return socket_method(*args, **kwargs)
        except (BlockingIOError, TimeoutError, InterruptedError):
            raise _WouldBlock(event) from None

    return _retry_impl(socket, timeout, retry_interval, callback)


def retry_ssl_socket_method(
    socket: _SSLSocket,
    timeout: float | None,
    retry_interval: float | None,
    socket_method: Callable[_P, _R],
    /,
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _R:
    assert is_ssl_socket(socket), "Expected a ssl.SSLSocket instance"  # nosec assert_used

    def callback() -> _R:
        assert ssl is not None, "stdlib ssl module not available"  # nosec assert_used
        try:
            return socket_method(*args, **kwargs)
        except (ssl.SSLWantReadError, ssl.SSLSyscallError):
            raise _WouldBlock("read") from None
        except ssl.SSLWantWriteError:
            raise _WouldBlock("write") from None

    return _retry_impl(socket, timeout, retry_interval, callback)


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


def ensure_datagram_socket_bound(sock: _socket.socket) -> None:
    check_socket_family(sock.family)
    if sock.type != _socket.SOCK_DGRAM:
        raise ValueError("Invalid socket type. Expected SOCK_DGRAM socket.")
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


@contextlib.contextmanager
def lock_with_timeout(
    lock: threading.RLock | threading.Lock,
    timeout: float | None,
    *,
    error_message: str = "timed out",
) -> Iterator[float | None]:
    if timeout is None:
        with lock:
            yield None
        return
    timeout = validate_timeout_delay(timeout, positive_check=False)
    with contextlib.ExitStack() as stack:
        # Try to acquire without blocking first
        if lock.acquire(blocking=False):
            stack.push(lock)
        else:
            _start = time.perf_counter()
            if timeout <= 0 or not lock.acquire(True, timeout):
                raise TimeoutError(error_message)
            stack.push(lock)
            _end = time.perf_counter()
            timeout -= _end - _start
        yield timeout if timeout > 0 else 0.0
