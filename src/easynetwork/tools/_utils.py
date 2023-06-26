# -*- coding: utf-8 -*-

from __future__ import annotations

__all__ = [
    "check_real_socket_state",
    "check_socket_family",
    "check_socket_no_ssl",
    "concatenate_chunks",
    "ensure_datagram_socket_bound",
    "error_from_errno",
    "is_ssl_eof_error",
    "is_ssl_socket",
    "open_listener_sockets_from_getaddrinfo_result",
    "replace_kwargs",
    "retry_socket_method",
    "retry_ssl_socket_method",
    "set_reuseport",
    "set_tcp_nodelay",
    "transform_future_exception",
    "wait_socket_available",
]

import concurrent.futures
import contextlib
import errno as _errno
import os
import selectors as _selectors
import socket as _socket
import time
import traceback
from struct import unpack
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, ParamSpec, TypeGuard, TypeVar, assert_never

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

    from .socket import SupportsSocketOptions

_P = ParamSpec("_P")
_R = TypeVar("_R")


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


def error_from_errno(errno: int) -> OSError:
    return OSError(errno, os.strerror(errno))


def check_socket_family(family: int) -> None:
    supported_families: dict[str, int] = dict(AddressFamily.__members__)

    if family not in list(supported_families.values()):
        raise ValueError(f"Only these families are supported: {', '.join(supported_families)}")


def check_real_socket_state(socket: SupportsSocketOptions) -> None:
    """Verify socket saved error and raise OSError if there is one

    There is some functions such as socket.send() which do not immediately fail and save the errno
    in SO_ERROR socket option because the error spawn after the action was sent to the kernel (Something weird)

    On Windows: The returned value should be the error returned by WSAGetLastError(), but the socket methods always call
    this function to raise an error, so getsockopt(SO_ERROR) will most likely always return zero :)
    """
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
    selector_cls: type[_selectors.BaseSelector] = getattr(_selectors, "PollSelector", _selectors.SelectSelector)

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
        return len(ready_list) > 0


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
    assert socket.gettimeout() == 0, "The socket must be non-blocking"
    assert retry_interval is None or retry_interval > 0, "retry_interval must be a strictly positive float or None"

    monotonic = time.monotonic  # pull function to local namespace
    event: Literal["read", "write"]
    if timeout == float("+inf"):
        timeout = None
    if retry_interval == float("+inf"):
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
        _start = monotonic()
        if not wait_socket_available(socket, wait_time, event):
            if not is_retry_interval:
                break
        _end = monotonic()
        if timeout is not None:
            timeout -= _end - _start
    raise error_from_errno(_errno.ETIMEDOUT)


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
    assert not is_ssl_socket(socket), "ssl.SSLSocket instances are forbidden"

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
    assert is_ssl_socket(socket), "Expected an ssl.SSLSocket instance"

    def callback() -> _R:
        assert ssl is not None, "stdlib ssl module not available"
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


def concatenate_chunks(chunks_iterable: Iterable[bytes]) -> bytes:
    return b"".join(chunks_iterable)


def iter_bytes(b: bytes | bytearray) -> Iterable[bytes]:
    return unpack(f"{len(b)}c", b)


def ensure_datagram_socket_bound(sock: _socket.socket) -> None:
    assert sock.family in (_socket.AF_INET, _socket.AF_INET6), "Invalid socket family."
    if sock.type != _socket.SOCK_DGRAM:
        raise ValueError("Invalid socket type. Expected SOCK_DGRAM socket.")
    try:
        is_bound: bool = sock.getsockname()[1] > 0
    except OSError as exc:
        if exc.errno != _errno.EINVAL:
            raise
        is_bound = False

    if not is_bound:
        sock.bind(("", 0))


def set_reuseport(sock: SupportsSocketOptions) -> None:
    if not hasattr(_socket, "SO_REUSEPORT"):
        raise ValueError("reuse_port not supported by socket module")
    else:
        try:
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, True)
        except OSError:
            raise ValueError("reuse_port not supported by socket module, SO_REUSEPORT defined but not implemented.") from None


def set_tcp_nodelay(sock: SupportsSocketOptions) -> None:
    try:
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, True)
    except (OSError, AttributeError):  # pragma: no cover
        pass


def set_tcp_keepalive(sock: SupportsSocketOptions) -> None:
    try:
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, True)
    except (OSError, AttributeError):  # pragma: no cover
        pass


def open_listener_sockets_from_getaddrinfo_result(
    infos: Iterable[tuple[int, int, int, str, tuple[Any, ...]]],
    *,
    backlog: int,
    reuse_address: bool,
    reuse_port: bool,
) -> list[_socket.socket]:
    sockets: list[_socket.socket] = []
    reuse_address = reuse_address and hasattr(_socket, "SO_REUSEADDR")
    with contextlib.ExitStack() as socket_exit_stack:
        errors: list[OSError] = []
        for af, _, proto, _, sa in infos:
            try:
                sock = socket_exit_stack.enter_context(contextlib.closing(_socket.socket(af, _socket.SOCK_STREAM, proto)))
            except OSError:
                # Assume it's a bad family/type/protocol combination.
                continue
            sockets.append(sock)
            if reuse_address:
                try:
                    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, True)
                except OSError:  # pragma: no cover
                    # Will fail later on bind()
                    pass
            if reuse_port:
                set_reuseport(sock)
            # Disable IPv4/IPv6 dual stack support (enabled by
            # default on Linux) which makes a single socket
            # listen on both address families.
            if _socket.has_ipv6 and af == _socket.AF_INET6 and hasattr(_socket, "IPPROTO_IPV6"):
                sock.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, True)
            try:
                sock.bind(sa)
            except OSError as exc:
                errors.append(
                    OSError(
                        exc.errno, "error while attempting to bind on address %r: %s" % (sa, exc.strerror.lower())
                    ).with_traceback(exc.__traceback__)
                )
                continue
            sock.listen(backlog)

        if errors:
            try:
                raise ExceptionGroup("Error when trying to create TCP listeners", errors)
            finally:
                errors = []

        # There were no errors, therefore do not close the sockets
        socket_exit_stack.pop_all()

    return sockets


def transform_future_exception(exc: BaseException) -> BaseException:
    match exc:
        case SystemExit() | KeyboardInterrupt():
            cancel_exc = concurrent.futures.CancelledError().with_traceback(exc.__traceback__)
            try:
                cancel_exc.__cause__ = cancel_exc.__context__ = exc
                exc = cancel_exc
            finally:
                del cancel_exc
        case _:
            pass
    return exc


def recursively_clear_exception_traceback_frames(exc: BaseException) -> None:
    traceback.clear_frames(exc.__traceback__)
    if exc.__context__ is not None:
        recursively_clear_exception_traceback_frames(exc.__context__)
    if exc.__cause__ is not exc.__context__ and exc.__cause__ is not None:
        recursively_clear_exception_traceback_frames(exc.__cause__)
