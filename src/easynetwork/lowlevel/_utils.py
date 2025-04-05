# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
    "Flag",
    "WarnCallback",
    "adjust_leftover_buffer",
    "check_inet_socket_family",
    "check_real_socket_state",
    "check_socket_no_ssl",
    "convert_socket_bind_error",
    "error_from_errno",
    "exception_with_notes",
    "get_callable_name",
    "is_ssl_eof_error",
    "is_ssl_socket",
    "iterate_exceptions",
    "lock_with_timeout",
    "make_callback",
    "missing_extra_deps",
    "open_listener_sockets_from_getaddrinfo_result",
    "prepend_argument",
    "remove_traceback_frames_in_place",
    "replace_kwargs",
    "set_reuseport",
    "supports_socket_sendmsg",
    "validate_listener_hosts",
    "validate_optional_timeout_delay",
    "validate_timeout_delay",
    "weak_method_proxy",
]

import contextlib
import errno as _errno
import functools
import math
import socket as _socket
import threading
import time
import weakref
from abc import abstractmethod
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, Protocol, Self, TypeGuard, TypeVar, overload

try:
    import ssl as _ssl
except ImportError:  # pragma: no cover
    ssl = None
else:
    ssl = _ssl
    del _ssl

from . import constants
from ._errno import error_from_errno

if TYPE_CHECKING:
    from ssl import SSLError as _SSLError, SSLSocket as _SSLSocket

    from _typeshed import ReadableBuffer

    from .socket import ISocket, SupportsSocketOptions

_P = ParamSpec("_P")
_T_Return = TypeVar("_T_Return")
_T_Arg = TypeVar("_T_Arg")

_T_Exception = TypeVar("_T_Exception", bound=BaseException)
_T_Func = TypeVar("_T_Func", bound=Callable[..., Any])


def replace_kwargs(kwargs: dict[str, Any], keys: dict[str, str]) -> None:
    if not keys:
        raise ValueError("Empty key dict")
    for old_key, new_key in keys.items():
        if new_key in kwargs:
            raise ValueError(f"Cannot set {old_key!r} to {new_key!r}: {new_key!r} in dictionary")
        try:
            kwargs[new_key] = kwargs.pop(old_key)
        except KeyError:
            pass


def make_callback(func: Callable[_P, _T_Return], /, *args: _P.args, **kwargs: _P.kwargs) -> Callable[[], _T_Return]:
    return functools.partial(func, *args, **kwargs)


@overload
def weak_method_proxy(weak_method: weakref.WeakMethod[Callable[_P, _T_Return]], /) -> Callable[_P, _T_Return]: ...


@overload
def weak_method_proxy(weak_method: Callable[_P, _T_Return], /) -> Callable[_P, _T_Return]: ...


def weak_method_proxy(
    weak_method: weakref.WeakMethod[Callable[_P, _T_Return]] | Callable[_P, _T_Return], /
) -> Callable[_P, _T_Return]:
    if not isinstance(weak_method, weakref.WeakMethod):
        weak_method = weakref.WeakMethod(weak_method)

    @functools.wraps(weak_method, assigned=(), updated=())
    def weak_method_proxy(*args: _P.args, **kwargs: _P.kwargs) -> _T_Return:
        method = weak_method()
        if method is None:
            raise ReferenceError("weakly-referenced object no longer exists")
        return method(*args, **kwargs)

    return weak_method_proxy


@overload
def prepend_argument(
    arg: _T_Arg,
    func: None = ...,
) -> Callable[[Callable[Concatenate[_T_Arg, _P], _T_Return]], Callable[_P, _T_Return]]: ...


@overload
def prepend_argument(
    arg: _T_Arg,
    func: Callable[Concatenate[_T_Arg, _P], _T_Return],
) -> Callable[_P, _T_Return]: ...


def prepend_argument(
    arg: _T_Arg,
    func: Callable[Concatenate[_T_Arg, _P], _T_Return] | None = None,
) -> Callable[[Callable[Concatenate[_T_Arg, _P], _T_Return]], Callable[_P, _T_Return]] | Callable[_P, _T_Return]:
    def decorator(func: Callable[Concatenate[_T_Arg, _P], _T_Return], /) -> Callable[_P, _T_Return]:
        return functools.partial(func, arg)

    if func is not None:
        return decorator(func)
    return decorator


def get_callable_name(func: Callable[..., Any]) -> str:
    while isinstance(func, functools.partial):
        func = func.func
    qualname: str | None = getattr(func, "__qualname__", None)
    if not qualname:
        qualname = getattr(func, "__name__", None)
        if not qualname:
            return ""
    module: str | None = getattr(func, "__module__", None)
    if not module:
        return qualname
    return f"{module}.{qualname}"


def inherit_doc(base_cls: type[Any]) -> Callable[[_T_Func], _T_Func]:
    assert isinstance(base_cls, type)  # nosec assert_used

    def decorator(dest_func: _T_Func) -> _T_Func:
        ref_func: Any = getattr(base_cls, dest_func.__name__)
        dest_func.__doc__ = ref_func.__doc__
        return dest_func

    return decorator


def missing_extra_deps(extra_name: str, *, feature_name: str = "") -> ModuleNotFoundError:
    if not feature_name:
        feature_name = extra_name
    return exception_with_notes(
        ModuleNotFoundError(f"{feature_name} dependencies are missing. Consider adding {extra_name!r} extra"),
        [f'example: pip install "easynetwork[{extra_name}]"'],
    )


def check_inet_socket_family(family: int) -> None:
    if family not in {_socket.AF_INET, _socket.AF_INET6}:
        raise ValueError("Only these families are supported: AF_INET, AF_INET6")


def check_real_socket_state(socket: ISocket, error_msg: str | None = None) -> None:
    """Verify socket saved error and raise OSError if there is one

    There are some functions such as socket.send() which do not immediately fail and save the errno
    in SO_ERROR socket option because the error spawns after the action was sent to the kernel (Something weird)

    On Windows: The returned value should be the error returned by WSAGetLastError(), but the socket methods always call
    this function to raise an error, so getsockopt(SO_ERROR) will most likely always return zero :)
    """
    if socket.fileno() < 0:
        return
    errno = socket.getsockopt(_socket.SOL_SOCKET, _socket.SO_ERROR)
    if errno != 0:
        # The SO_ERROR is automatically reset to zero after getting the value
        if error_msg:
            raise error_from_errno(errno, error_msg)
        else:
            raise error_from_errno(errno)


class _SupportsSocketSendMSG(Protocol):
    @abstractmethod
    def sendmsg(self, buffers: Iterable[ReadableBuffer], /) -> int: ...


def supports_socket_sendmsg(sock: _socket.socket) -> TypeGuard[_SupportsSocketSendMSG]:
    assert isinstance(sock, _socket.SocketType)  # nosec assert_used
    return hasattr(sock, "sendmsg")


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
    if positive_check and delay < 0.0:
        raise ValueError("Invalid delay: negative value")
    return float(delay)


def validate_optional_timeout_delay(delay: float | None, *, positive_check: bool) -> float:
    match delay:
        case None:
            return math.inf
        case _:
            return validate_timeout_delay(delay, positive_check=positive_check)


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


def adjust_leftover_buffer(buffers: deque[memoryview], nbytes: int) -> None:
    while nbytes > 0:
        b = buffers.popleft()
        if b.itemsize != 1:
            b = b.cast("B")
        b_len = len(b)
        if b_len <= nbytes:
            nbytes -= b_len
        else:
            buffers.appendleft(b[nbytes:])
            break


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


def set_reuseport(sock: SupportsSocketOptions) -> None:
    if hasattr(_socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, True)
        except OSError:
            raise ValueError("reuse_port not supported by socket module, SO_REUSEPORT defined but not implemented.") from None
    else:
        raise ValueError("reuse_port not supported by socket module")


def validate_listener_hosts(host: str | Sequence[str] | None) -> list[str | None]:
    match host:
        case "" | None:
            return [None]
        case str():
            return [host]
        case _ if all(isinstance(h, str) for h in host):
            return list(host)
        case _:
            raise TypeError(host)


def open_listener_sockets_from_getaddrinfo_result(
    infos: Iterable[tuple[int, int, int, str, tuple[Any, ...]]],
    *,
    reuse_address: bool,
    reuse_port: bool,
) -> list[_socket.socket]:
    sockets: list[_socket.socket] = []
    reuse_address = reuse_address and hasattr(_socket, "SO_REUSEADDR")
    with contextlib.ExitStack() as _whole_context_stack:
        errors: list[OSError] = []
        _whole_context_stack.callback(errors.clear)

        socket_exit_stack = _whole_context_stack.enter_context(contextlib.ExitStack())

        for af, socktype, proto, _, sa in infos:
            try:
                sock = socket_exit_stack.enter_context(contextlib.closing(_socket.socket(af, socktype, proto)))
            except OSError:
                # Assume it's a bad family/type/protocol combination.
                continue
            sockets.append(sock)
            if reuse_address:
                try:
                    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, True)
                except OSError:
                    # Will fail later on bind()
                    pass
            if reuse_port:
                set_reuseport(sock)
            # Disable IPv4/IPv6 dual stack support (enabled by
            # default on Linux) which makes a single socket
            # listen on both address families.
            if af == _socket.AF_INET6:
                if hasattr(_socket, "IPPROTO_IPV6"):
                    sock.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, True)
                if "%" in sa[0]:
                    addr, scope_id = sa[0].split("%", 1)
                    sa = (addr, sa[1], 0, int(scope_id))
            try:
                sock.bind(sa)
            except OSError as exc:
                errors.append(convert_socket_bind_error(exc, sa))
                continue

        if errors:
            # No need to call errors.clear(), this is done by exit stack
            raise ExceptionGroup("Error when trying to create listeners", errors)

        # There were no errors, therefore do not close the sockets
        socket_exit_stack.pop_all()

    return sockets


def convert_socket_bind_error(exc: OSError, addr: Any) -> OSError:
    if exc.errno:
        msg = f"error while attempting to bind on address {addr!r}: {exc.strerror}"
        return OSError(exc.errno, msg).with_traceback(exc.__traceback__)
    else:
        msg = f"error while attempting to bind on address {addr!r}: {exc}"
        return OSError(_errno.EINVAL, msg).with_traceback(exc.__traceback__)


def exception_with_notes(exc: _T_Exception, notes: str | Iterable[str]) -> _T_Exception:
    if isinstance(notes, str):
        notes = (notes,)
    for note in notes:
        exc.add_note(note)
    return exc


def remove_traceback_frames_in_place(exc: _T_Exception, n: int) -> _T_Exception:
    tb = exc.__traceback__
    for _ in range(n):
        if tb is None:
            break
        tb = tb.tb_next
    return exc.with_traceback(tb)


def iterate_exceptions(exception: BaseException) -> Iterator[BaseException]:
    if isinstance(exception, BaseExceptionGroup):
        for exc in exception.exceptions:
            yield from iterate_exceptions(exc)
    else:
        yield exception


class WarnCallback(Protocol):
    @overload
    @abstractmethod
    def __call__(
        self,
        /,
        message: str,
        category: type[Warning] | None = None,
        stacklevel: int = 1,
        source: Any | None = None,
    ) -> None: ...

    @overload
    @abstractmethod
    def __call__(
        self,
        /,
        message: Warning,
        category: Any = None,
        stacklevel: int = 1,
        source: Any | None = None,
    ) -> None: ...


class Flag:
    __slots__ = ("__value", "__weakref__")

    def __init__(self) -> None:
        self.__value: bool = False

    def is_set(self) -> bool:
        return self.__value

    def set(self) -> None:
        self.__value = True

    def clear(self) -> None:
        self.__value = False


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


class lock_with_timeout(contextlib.AbstractContextManager[float | None, None]):
    __slots__ = ("__lock", "__timeout")

    def __init__(self, lock: threading.RLock | threading.Lock, timeout: float | None) -> None:
        if timeout is not None:
            timeout = validate_timeout_delay(timeout, positive_check=True)
        self.__lock = lock
        self.__timeout = timeout

    def __enter__(self) -> float | None:
        lock = self.__lock
        match self.__timeout:
            case None | math.inf as timeout:
                lock.acquire()
                return timeout
            case timeout:
                # Try to acquire without blocking first
                if not lock.acquire(blocking=False):
                    if timeout == 0.0:
                        raise error_from_errno(_errno.ETIMEDOUT)
                    with ElapsedTime() as elapsed:
                        if not lock.acquire(blocking=True, timeout=timeout):
                            raise error_from_errno(_errno.ETIMEDOUT)
                    timeout = elapsed.recompute_timeout(timeout)
                return timeout

    def __exit__(self, *args: Any) -> None:
        self.__lock.release()


class ResourceGuard:
    __slots__ = (
        "__held",
        "__msg",
    )

    def __init__(self, message: str) -> None:
        self.__held: bool = False
        self.__msg = message

    def __enter__(self) -> None:
        if self.__held:
            from ..exceptions import BusyResourceError

            msg = self.__msg
            raise BusyResourceError(msg)
        self.__held = True

    def __exit__(self, *args: Any) -> None:
        if not self.__held:
            raise AssertionError("ResourceGuard released too many times")
        self.__held = False
