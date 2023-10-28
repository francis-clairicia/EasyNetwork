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
"""Network socket module"""

from __future__ import annotations

__all__ = [
    "AddressFamily",
    "INETSocketAttribute",
    "IPv4SocketAddress",
    "IPv6SocketAddress",
    "ISocket",
    "SocketAttribute",
    "SocketProxy",
    "SupportsSocketOptions",
    "TLSAttribute",
    "_get_socket_extra",
    "_get_tls_extra",
    "disable_socket_linger",
    "enable_socket_linger",
    "get_socket_linger_struct",
    "new_socket_address",
    "set_tcp_keepalive",
    "set_tcp_nodelay",
]

import contextlib
import functools
import os
import socket as _socket
import threading
from collections.abc import Callable
from enum import IntEnum, unique
from struct import Struct
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NamedTuple,
    ParamSpec,
    Protocol,
    TypeAlias,
    TypeVar,
    assert_never,
    final,
    overload,
    runtime_checkable,
)

from . import typed_attr

if TYPE_CHECKING:
    import ssl as _typing_ssl

_P = ParamSpec("_P")
_R = TypeVar("_R")


class SocketAttribute(typed_attr.TypedAttributeSet):
    __slots__ = ()

    socket: ISocket = typed_attr.typed_attribute()
    """:class:`socket.socket` instance."""

    family: int = typed_attr.typed_attribute()
    """the socket's family, as returned by :attr:`socket.socket.family`."""

    sockname: _socket._RetAddress = typed_attr.typed_attribute()
    """the socket's own address, result of :meth:`socket.socket.getsockname`."""

    peername: _socket._RetAddress = typed_attr.typed_attribute()
    """the remote address to which the socket is connected, result of :meth:`socket.socket.getpeername`."""


class INETSocketAttribute(SocketAttribute):
    __slots__ = ()

    family: Literal[_socket.AddressFamily.AF_INET, _socket.AddressFamily.AF_INET6]
    """the socket's family, as returned by :attr:`socket.socket.family`."""

    sockname: tuple[str, int] | tuple[str, int, int, int]
    """the socket's own address, result of :meth:`socket.socket.getsockname`."""

    peername: tuple[str, int] | tuple[str, int, int, int]
    """the remote address to which the socket is connected, result of :meth:`socket.socket.getpeername`."""


class TLSAttribute(typed_attr.TypedAttributeSet):
    __slots__ = ()

    sslcontext: _typing_ssl.SSLContext = typed_attr.typed_attribute()
    """:class:`ssl.SSLContext` instance."""

    peercert: _typing_ssl._PeerCertRetDictType = typed_attr.typed_attribute()
    """peer certificate; result of :meth:`ssl.SSLSocket.getpeercert`."""

    cipher: tuple[str, str, int] = typed_attr.typed_attribute()
    """a three-value tuple containing the name of the cipher being used, the version of the SSL protocol
    that defines its use, and the number of secret bits being used; result of :meth:`ssl.SSLSocket.cipher`."""

    compression: str = typed_attr.typed_attribute()
    """the compression algorithm being used as a string, or None if the connection isn't compressed;
    result of :meth:`ssl.SSLSocket.compression`."""

    standard_compatible: bool = typed_attr.typed_attribute()
    """:data:`True` if this stream does (and expects) a closing TLS handshake when the stream is being closed."""

    tls_version: str = typed_attr.typed_attribute()
    """the TLS protocol version (e.g. TLSv1.2)"""


@unique
class AddressFamily(IntEnum):
    """
    Enumeration of supported socket address families.
    """

    AF_INET = _socket.AF_INET
    AF_INET6 = _socket.AF_INET6

    def __repr__(self) -> str:
        return f"{type(self).__name__}.{self.name}"

    def __str__(self) -> str:  # pragma: no cover
        return repr(self)


class IPv4SocketAddress(NamedTuple):
    host: str
    port: int

    def __str__(self) -> str:  # pragma: no cover
        return f"({self.host!r}, {self.port:d})"

    def for_connection(self) -> tuple[str, int]:
        """
        Returns:
            A pair of (host, port)
        """
        return self.host, self.port


class IPv6SocketAddress(NamedTuple):
    host: str
    port: int
    flowinfo: int = 0
    scope_id: int = 0

    def __str__(self) -> str:  # pragma: no cover
        return f"({self.host!r}, {self.port:d})"

    def for_connection(self) -> tuple[str, int]:
        """
        Returns:
            A pair of (host, port)
        """
        return self.host, self.port


SocketAddress: TypeAlias = IPv4SocketAddress | IPv6SocketAddress
"""Alias for :class:`IPv4SocketAddress` | :class:`IPv6SocketAddress`"""


@overload
def new_socket_address(addr: tuple[str, int], family: Literal[AddressFamily.AF_INET]) -> IPv4SocketAddress:
    ...


@overload
def new_socket_address(
    addr: tuple[str, int] | tuple[str, int, int, int], family: Literal[AddressFamily.AF_INET6]
) -> IPv6SocketAddress:
    ...


@overload
def new_socket_address(addr: tuple[Any, ...], family: int) -> SocketAddress:
    ...


def new_socket_address(addr: tuple[Any, ...], family: int) -> SocketAddress:
    """
    Factory to create a :data:`SocketAddress` from `addr`.

    Example:
        >>> import socket
        >>> new_socket_address(("127.0.0.1", 12345), socket.AF_INET)
        IPv4SocketAddress(host='127.0.0.1', port=12345)
        >>> new_socket_address(("::1", 12345), socket.AF_INET6)
        IPv6SocketAddress(host='::1', port=12345, flowinfo=0, scope_id=0)
        >>> new_socket_address(("::1", 12345, 12, 345), socket.AF_INET6)
        IPv6SocketAddress(host='::1', port=12345, flowinfo=12, scope_id=345)
        >>> new_socket_address(("127.0.0.1", 12345), socket.AF_APPLETALK)
        Traceback (most recent call last):
        ...
        ValueError: <AddressFamily.AF_APPLETALK: 5> is not a valid AddressFamily

    Parameters:
        addr: The address in the form ``(host, port)`` or ``(host, port, flow, scope_id)``.
        family: The socket family.

    Raises:
        ValueError: Invalid `family`.
        TypeError: Invalid `addr`.

    Returns:
        a :data:`SocketAddress` named tuple.
    """
    family = AddressFamily(family)
    match family:
        case AddressFamily.AF_INET:
            return IPv4SocketAddress(*addr)
        case AddressFamily.AF_INET6:
            return IPv6SocketAddress(*addr)
        case _:  # pragma: no cover
            assert_never(family)


@runtime_checkable
class SupportsSocketOptions(Protocol):
    @overload
    def getsockopt(self, level: int, optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, level: int, optname: int, buflen: int, /) -> bytes:
        ...

    def getsockopt(self, *args: Any) -> int | bytes:  # pragma: no cover
        """
        Similar to :meth:`socket.socket.getsockopt`.
        """
        ...

    @overload
    def setsockopt(self, level: int, optname: int, value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, level: int, optname: int, value: None, optlen: int, /) -> None:
        ...

    def setsockopt(self, *args: Any) -> None:  # pragma: no cover
        """
        Similar to :meth:`socket.socket.setsockopt`.
        """
        ...


@runtime_checkable
class ISocket(SupportsSocketOptions, Protocol):
    def fileno(self) -> int:  # pragma: no cover
        """
        Similar to :meth:`socket.socket.fileno`.
        """
        ...

    def get_inheritable(self) -> bool:  # pragma: no cover
        """
        Similar to :meth:`socket.socket.get_inheritable`.
        """
        ...

    def getpeername(self) -> _socket._RetAddress:  # pragma: no cover
        """
        Similar to :meth:`socket.socket.getpeername`.
        """
        ...

    def getsockname(self) -> _socket._RetAddress:  # pragma: no cover
        """
        Similar to :meth:`socket.socket.getsockname`.
        """
        ...

    @property  # pragma: no cover
    def family(self) -> int:
        """
        Similar to :attr:`socket.socket.family`.
        """
        ...

    @property  # pragma: no cover
    def type(self) -> int:
        """
        Similar to :attr:`socket.socket.type`.
        """
        ...

    @property  # pragma: no cover
    def proto(self) -> int:
        """
        Similar to :attr:`socket.socket.proto`.
        """
        ...


@final
class SocketProxy:
    """
    A socket-like wrapper for exposing real transport sockets.

    These objects can be safely returned by APIs like
    `client.socket`.  All potentially disruptive
    operations (like :meth:`socket.socket.close`) are banned.
    """

    __slots__ = ("__socket", "__lock_ctx", "__runner", "__weakref__")

    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError("SocketProxy cannot be subclassed")

    def __init__(
        self,
        socket: ISocket,
        *,
        lock: Callable[[], threading.Lock | threading.RLock] | None = None,
        runner: Callable[[Callable[[], Any]], Any] | None = None,
    ) -> None:
        """
        Parameters:
            socket: The socket-like object to wrap.
            lock: A callback function to use when a lock is required to gain access to the wrapped socket.
            runner: A callback function to use to execute the socket method.

        Warning:
            If `lock` is ommitted, the proxy object is *not* thread-safe.

            `runner` can be used for concurrent call management.

        Example:
            Examples of how :meth:`ISocket.fileno` would be called according to `lock` and `runner` values.

            Neither `lock` nor `runner`::

                return socket.fileno()

            `lock` but no `runner`::

                with lock():
                    return socket.fileno()

            `runner` but no `lock`::

                return runner(socket.fileno)

            Both `lock` and `runner`::

                with lock():
                    return runner(socket.fileno)
        """
        self.__socket: ISocket = socket
        self.__lock_ctx: Callable[[], threading.Lock | threading.RLock] | None = lock
        self.__runner: Callable[[Callable[[], Any]], Any] | None = runner

    def __repr__(self) -> str:
        fd: int = self.fileno()
        s = f"<{type(self).__name__} fd={fd}, " f"family={self.family!s}, type={self.type!s}, " f"proto={self.proto}"

        if fd != -1:
            try:
                laddr = self.getsockname()
                if laddr:
                    s = f"{s}, laddr={laddr}"
            except _socket.error:
                pass
            try:
                raddr = self.getpeername()
                if raddr:
                    s = f"{s}, raddr={raddr}"
            except _socket.error:
                pass

        return f"{s}>"

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    def __execute(self, func: Callable[_P, _R], /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with lock_ctx() if (lock_ctx := self.__lock_ctx) is not None else contextlib.nullcontext():
            if (run := self.__runner) is not None:
                if args or kwargs:
                    func = functools.partial(func, *args, **kwargs)
                return run(func)
            return func(*args, **kwargs)

    def fileno(self) -> int:
        """
        Calls :meth:`ISocket.fileno`.
        """
        return self.__execute(self.__socket.fileno)

    def get_inheritable(self) -> bool:
        """
        Calls :meth:`ISocket.get_inheritable`.
        """
        return self.__execute(self.__socket.get_inheritable)

    @overload
    def getsockopt(self, level: int, optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, level: int, optname: int, buflen: int, /) -> bytes:
        ...

    def getsockopt(self, *args: Any) -> int | bytes:
        """
        Calls :meth:`ISocket.getsockopt <SupportsSocketOptions.getsockopt>`.
        """
        return self.__execute(self.__socket.getsockopt, *args)

    @overload
    def setsockopt(self, level: int, optname: int, value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, level: int, optname: int, value: None, optlen: int, /) -> None:
        ...

    def setsockopt(self, *args: Any) -> None:
        """
        Calls :meth:`ISocket.setsockopt <SupportsSocketOptions.setsockopt>`.
        """
        return self.__execute(self.__socket.setsockopt, *args)

    def getpeername(self) -> _socket._RetAddress:
        """
        Calls :meth:`ISocket.getpeername`.
        """
        return self.__execute(self.__socket.getpeername)

    def getsockname(self) -> _socket._RetAddress:
        """
        Calls :meth:`ISocket.getsockname`.
        """
        return self.__execute(self.__socket.getsockname)

    @property
    def family(self) -> int:
        """The socket family."""
        family: int = self.__socket.family
        return _cast_socket_family(family)

    @property
    def type(self) -> int:
        """The socket type."""
        socket_type = self.__socket.type
        return _cast_socket_kind(socket_type)

    @property
    def proto(self) -> int:
        """The socket protocol."""
        return self.__socket.proto


def set_tcp_nodelay(sock: SupportsSocketOptions, state: bool) -> None:
    """
    Enables/Disable Nagle's algorithm on a TCP socket.

    This is equivalent to::

        sock.setsockopt(IPPROTO_TCP, TCP_NODELAY, state)

    *except* that if :data:`socket.TCP_NODELAY` is not defined, it is silently ignored.

    Parameters:
        sock: The socket.
        state: :data:`True` to disable, :data:`False` to enable.

    Note:
        Modern operating systems enable it by default.
    """
    state = bool(state)
    with contextlib.suppress(AttributeError):
        sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, state)


def set_tcp_keepalive(sock: SupportsSocketOptions, state: bool) -> None:
    """
    Enables/Disable keep-alive protocol on a TCP socket.

    This is equivalent to::

        sock.setsockopt(SOL_SOCKET, SO_KEEPALIVE, state)

    *except* that if :data:`socket.SO_KEEPALIVE` is not defined, it is silently ignored.

    Parameters:
        sock: The socket.
        state: :data:`True` to enable, :data:`False` to disable.

    Note:
        Modern operating systems enable it by default.
    """
    state = bool(state)
    with contextlib.suppress(AttributeError):
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, state)


if os.name == "nt":  # Windows
    # https://learn.microsoft.com/en-us/windows/win32/api/winsock2/ns-winsock2-linger
    # linger struct uses unsigned short ints
    _linger_struct = Struct("@HH")
else:  # Unix/macOS
    # https://manpages.debian.org/bookworm/manpages/socket.7.en.html#SO_LINGER
    # linger struct uses signed ints
    _linger_struct = Struct("@ii")


def get_socket_linger_struct() -> Struct:
    """
    Returns a :class:`~struct.Struct` representation of the SO_LINGER structure. See :manpage:`socket(7)` for details.

    The format of the returned struct may vary depending on the operating system.
    """
    return _linger_struct


def enable_socket_linger(sock: SupportsSocketOptions, timeout: int) -> None:
    """
    Enables socket linger.

    This is equivalent to::

        sock.setsockopt(SOL_SOCKET, SO_LINGER, linger_struct)

    ``linger_struct`` is determined by the operating system. See :func:`get_socket_linger_struct` for details.

    See the Unix manual page :manpage:`socket(7)` for the meaning of the argument `timeout`.

    Parameters:
        sock: The socket.
        timeout: The linger timeout.

    Note:
        Modern operating systems disable it by default.

    See Also:
        :func:`disable_socket_linger`
    """
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER, _linger_struct.pack(True, timeout))


def disable_socket_linger(sock: SupportsSocketOptions) -> None:
    """
    Disables socket linger.

    This is equivalent to::

        sock.setsockopt(SOL_SOCKET, SO_LINGER, linger_struct)

    ``linger_struct`` is determined by the operating system. See :func:`get_socket_linger_struct` for details.

    Parameters:
        sock: The socket.

    Note:
        Modern operating systems disable it by default.

    See Also:
        :func:`enable_socket_linger`
    """
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER, _linger_struct.pack(False, 0))


def _get_socket_extra(sock: ISocket, *, wrap_in_proxy: bool = True) -> dict[Any, Callable[[], Any]]:
    return {
        SocketAttribute.socket: (lambda: sock) if not wrap_in_proxy else (lambda: SocketProxy(sock)),
        SocketAttribute.family: lambda: _cast_socket_family(sock.family),
        SocketAttribute.sockname: lambda: _address_or_lookup_error(sock.getsockname),
        SocketAttribute.peername: lambda: _address_or_lookup_error(sock.getpeername),
    }


def _get_tls_extra(ssl_object: _typing_ssl.SSLObject | _typing_ssl.SSLSocket) -> dict[Any, Callable[[], Any]]:
    return {
        TLSAttribute.sslcontext: lambda: ssl_object.context,
        TLSAttribute.peercert: lambda: _value_or_lookup_error(ssl_object.getpeercert()),
        TLSAttribute.cipher: lambda: _value_or_lookup_error(ssl_object.cipher()),
        TLSAttribute.compression: lambda: _value_or_lookup_error(ssl_object.compression()),
        TLSAttribute.tls_version: lambda: _value_or_lookup_error(ssl_object.version()),
    }


def _cast_socket_family(family: int) -> int:
    try:
        return _socket.AddressFamily(family)
    except ValueError:
        return family


def _cast_socket_kind(kind: int) -> int:
    try:
        return _socket.SocketKind(kind)
    except ValueError:
        return kind


def _address_or_lookup_error(getsockaddr: Callable[[], _R]) -> _R:
    try:
        return getsockaddr()
    except OSError as exc:
        from ..exceptions import TypedAttributeLookupError

        raise TypedAttributeLookupError("address not available") from exc


def _value_or_lookup_error(value: _R | None) -> _R:
    if value is None:
        from ..exceptions import TypedAttributeLookupError

        raise TypedAttributeLookupError("value not available")
    return value
