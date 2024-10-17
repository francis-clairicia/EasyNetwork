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
"""Network socket helper module."""

from __future__ import annotations

__all__ = [
    "INETSocketAttribute",
    "IPv4SocketAddress",
    "IPv6SocketAddress",
    "ISocket",
    "SocketAddress",
    "SocketAttribute",
    "SocketProxy",
    "SupportsSocketOptions",
    "TLSAttribute",
    "UNIXSocketAttribute",
    "UnixCredentials",
    "UnixSocketAddress",
    "_get_socket_extra",
    "_get_tls_extra",
    "disable_socket_linger",
    "enable_socket_linger",
    "get_socket_linger",
    "get_socket_linger_struct",
    "new_socket_address",
    "set_tcp_keepalive",
    "set_tcp_nodelay",
    "socket_linger",
]

import contextlib
import functools
import os
import pathlib
import socket as _socket
import sys
import threading
from abc import abstractmethod
from collections.abc import Callable
from struct import Struct
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NamedTuple,
    ParamSpec,
    Protocol,
    Self,
    TypeAlias,
    TypeVar,
    final,
    overload,
    runtime_checkable,
)

from . import typed_attr
from ._final import runtime_final_class

if TYPE_CHECKING:
    from socket import _RetAddress
    from ssl import SSLContext, SSLObject, SSLSocket, _PeerCertRetDictType

_P = ParamSpec("_P")
_T_Return = TypeVar("_T_Return")


class SocketAttribute(typed_attr.TypedAttributeSet):
    """Typed attributes which can be used on an endpoint or a transport."""

    __slots__ = ()

    socket: ISocket = typed_attr.typed_attribute()
    """:class:`socket.socket` instance."""

    family: int = typed_attr.typed_attribute()
    """the socket's family, as returned by :attr:`socket.socket.family`."""

    sockname: _RetAddress = typed_attr.typed_attribute()
    """the socket's own address, result of :meth:`socket.socket.getsockname`."""

    peername: _RetAddress = typed_attr.typed_attribute()
    """the remote address to which the socket is connected, result of :meth:`socket.socket.getpeername`."""


class INETSocketAttribute(SocketAttribute):
    """Typed attributes which can be used on an endpoint or a transport."""

    __slots__ = ()

    family: Literal[_socket.AddressFamily.AF_INET, _socket.AddressFamily.AF_INET6]
    """the socket's family, as returned by :attr:`socket.socket.family`."""

    sockname: tuple[str, int] | tuple[str, int, int, int]
    """the socket's own address, result of :meth:`socket.socket.getsockname`."""

    peername: tuple[str, int] | tuple[str, int, int, int]
    """the remote address to which the socket is connected, result of :meth:`socket.socket.getpeername`."""


class UNIXSocketAttribute(SocketAttribute):
    """
    Typed attributes which can be used on an endpoint or a transport.

    .. versionadded:: 1.1
    """

    __slots__ = ()

    if sys.platform != "win32":

        family: Literal[_socket.AddressFamily.AF_UNIX]
        """the socket's family, as returned by :attr:`socket.socket.family`."""

        if sys.platform == "linux":
            # Abstract Unix socket addresses are returned as bytes.

            sockname: str | bytes
            """the socket's own address, result of :meth:`socket.socket.getsockname`."""

            peername: str | bytes
            """the remote address to which the socket is connected, result of :meth:`socket.socket.getpeername`."""

        else:
            sockname: str
            """the socket's own address, result of :meth:`socket.socket.getsockname`."""

            peername: str
            """the remote address to which the socket is connected, result of :meth:`socket.socket.getpeername`."""


class TLSAttribute(typed_attr.TypedAttributeSet):
    """Typed attributes which can be used on an endpoint or a transport."""

    __slots__ = ()

    sslcontext: SSLContext = typed_attr.typed_attribute()
    """:class:`ssl.SSLContext` instance."""

    peercert: _PeerCertRetDictType = typed_attr.typed_attribute()
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
    """the TLS protocol version (e.g. TLSv1.2)."""


class IPv4SocketAddress(NamedTuple):
    """An internet (IPv4) socket address."""

    host: str
    port: int

    def __str__(self) -> str:
        return f"({self.host!r}, {self.port:d})"

    def for_connection(self) -> tuple[str, int]:
        """
        Returns:
            A pair of (host, port)
        """
        return self.host, self.port


class IPv6SocketAddress(NamedTuple):
    """An internet (IPv6) socket address."""

    host: str
    port: int
    flowinfo: int = 0
    scope_id: int = 0

    def __str__(self) -> str:
        return f"({self.host!r}, {self.port:d})"

    def for_connection(self) -> tuple[str, int]:
        """
        Returns:
            A pair of (host, port)
        """
        return self.host, self.port


SocketAddress: TypeAlias = IPv4SocketAddress | IPv6SocketAddress
"""An internet socket address, either IPv4 or IPv6."""


@overload
def new_socket_address(addr: tuple[str, int], family: Literal[_socket.AddressFamily.AF_INET]) -> IPv4SocketAddress: ...


@overload
def new_socket_address(
    addr: tuple[str, int] | tuple[str, int, int, int], family: Literal[_socket.AddressFamily.AF_INET6]
) -> IPv6SocketAddress: ...


@overload
def new_socket_address(addr: tuple[Any, ...], family: int) -> SocketAddress: ...


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
        ValueError: Unsupported address family <AddressFamily.AF_APPLETALK: 5>

    Parameters:
        addr: The address in the form ``(host, port)`` or ``(host, port, flow, scope_id)``.
        family: The socket family.

    Raises:
        ValueError: Invalid `family`.
        TypeError: Invalid `addr`.

    Returns:
        a :data:`SocketAddress` named tuple.
    """
    match family:
        case _socket.AddressFamily.AF_INET:
            return IPv4SocketAddress(*addr)
        case _socket.AddressFamily.AF_INET6:
            return IPv6SocketAddress(*addr)
        case _:
            raise ValueError(f"Unsupported address family {family!r}")


@final
@runtime_final_class
class UnixSocketAddress:
    """
    An address associated with a Unix socket.

    .. versionadded:: 1.1
    """

    __slots__ = ("__addr",)

    def __init__(self) -> None:
        """
        Constructs an unnamed socket address::

            >>> addr = UnixSocketAddress()
            >>> addr
            UnixSocketAddress(<unnamed>)
            >>> addr.is_unnamed()
            True
        """
        self.__addr: str | bytes | None = None

    @classmethod
    def from_pathname(cls, path: str | os.PathLike[str]) -> Self:
        """
        Constructs a :class:`UnixSocketAddress` with the provided path.

        Examples:

            >>> addr = UnixSocketAddress.from_pathname("/path/to/socket")
            >>> addr
            UnixSocketAddress('/path/to/socket' <pathname>)
            >>> addr.as_pathname()
            PosixPath('/path/to/socket')

            Creating a :class:`UnixSocketAddress` with a NULL byte results in an error.

            >>> addr = UnixSocketAddress.from_pathname("/path/with/\\0/bytes")
            Traceback (most recent call last):
            ...
            ValueError: paths must not contain interior null bytes

            Creating a :class:`UnixSocketAddress` with an empty string results in an unnamed socket address.

            >>> addr = UnixSocketAddress.from_pathname("")
            >>> addr
            UnixSocketAddress(<unnamed>)
            >>> addr.is_unnamed()
            True
        """
        path = os.fspath(path)
        if not isinstance(path, str):
            raise TypeError(f"Expected a str object or an os.PathLike object, got {path!r}")
        return cls.__from_pathname_unchecked(path)

    @classmethod
    def __from_pathname_unchecked(cls, path: str) -> Self:
        if "\0" in path:
            raise ValueError("paths must not contain interior null bytes")
        self = cls()
        self.__addr = path or None
        return self

    @classmethod
    def from_abstract_name(cls, name: str | bytes) -> Self:
        """
        Creates a Unix socket address in the abstract namespace.

        The abstract namespace is a Linux-specific extension that allows Unix sockets to be bound
        without creating an entry in the filesystem. Abstract sockets are unaffected by filesystem layout or permissions,
        and no cleanup is necessary when the socket is closed.

        An abstract socket address name may contain any bytes, including zero.

        Examples:

            >>> addr = UnixSocketAddress.from_abstract_name("hidden")
            >>> addr
            UnixSocketAddress(b'hidden' <abstract>)
            >>> addr.as_abstract_name()
            b'hidden'
        """
        if not isinstance(name, (str, bytes)):
            raise TypeError(f"Expected a str object or a bytes object, got {name!r}")
        name = os.fsencode(name)
        return cls.__from_abstract_name_unchecked(b"\0" + name)

    @classmethod
    def __from_abstract_name_unchecked(cls, name: bytes) -> Self:
        assert name[0] == 0, "Should start with a NUL byte."  # nosec assert_used
        self = cls()
        self.__addr = name
        return self

    @classmethod
    def from_raw(cls, addr: Any) -> Self:
        """
        Constructs a :class:`UnixSocketAddress` from the raw `addr` supplied by the :class:`~socket.socket`.

        * the result of :meth:`socket.socket.getsockname` or :meth:`socket.socket.getpeername`;

        * the address retrieved by :meth:`socket.socket.recvfrom`;

        * etc.
        """
        match addr:
            case str():
                if addr and addr[0] == "\0":
                    return cls.__from_abstract_name_unchecked(os.fsencode(addr))
                else:
                    return cls.__from_pathname_unchecked(addr)
            case bytes():
                if addr and addr[0] == 0:
                    return cls.__from_abstract_name_unchecked(addr)
                else:
                    return cls.__from_pathname_unchecked(os.fsdecode(addr))
            case _:
                raise TypeError(f"Cannot convert {addr!r} to a {cls.__name__}")

    def __repr__(self) -> str:
        match self.__addr:
            case str(addr):
                return f"{self.__class__.__name__}({addr!r} <pathname>)"
            case bytes(addr):
                return f"{self.__class__.__name__}({addr[1:]!r} <abstract>)"
            case _:
                return f"{self.__class__.__name__}(<unnamed>)"

    def __str__(self) -> str:
        match self.__addr:
            case str(addr):
                return f"{addr} (pathname)"
            case bytes(addr):
                return f"{addr[1:]!r} (abstract)"
            case _:
                return "(unnamed)"

    def __hash__(self) -> int:
        return hash(self.__addr)

    def __eq__(self, other: object) -> bool:
        match other:
            case UnixSocketAddress():
                return self.__addr == other.__addr
            case _:
                return NotImplemented

    def is_unnamed(self) -> bool:
        """
        Returns :data:`True` if the address is ``unnamed``.

        Examples:

            A named address:

            >>> import socket                                         # doctest: +SKIP
            >>> s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) # doctest: +SKIP
            >>> s.bind("/tmp/sock")                                   # doctest: +SKIP
            >>> addr = UnixSocketAddress.from_raw(s.getsockname())    # doctest: +SKIP
            >>> addr.is_unnamed()                                     # doctest: +SKIP
            False

            An unnamed address:

            >>> import socket
            >>> s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            >>> addr = UnixSocketAddress.from_raw(s.getsockname())
            >>> addr.is_unnamed()
            True
        """
        return self.__addr is None

    def as_pathname(self) -> pathlib.Path | None:
        """
        Returns the contents of this address if it is a ``pathname`` address.

        Examples:

            With a pathname:

            >>> import socket                                         # doctest: +SKIP
            >>> s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) # doctest: +SKIP
            >>> s.bind("/tmp/sock")                                   # doctest: +SKIP
            >>> addr = UnixSocketAddress.from_raw(s.getsockname())    # doctest: +SKIP
            >>> addr.as_pathname()                                    # doctest: +SKIP
            PosixPath('/tmp/sock')

            Without a pathname:

            >>> import socket
            >>> s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            >>> addr = UnixSocketAddress.from_raw(s.getsockname())
            >>> print(addr.as_pathname())
            None
        """
        match self.__addr:
            case str(addr):
                return pathlib.Path(addr)
            case _:
                return None

    def as_abstract_name(self) -> bytes | None:
        """
        Returns the contents of this address if it is in the abstract namespace.

        Examples:

            >>> import socket
            >>> s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            >>> s.bind(b"\\0hidden")
            >>> addr = UnixSocketAddress.from_raw(s.getsockname())
            >>> addr.as_abstract_name()
            b'hidden'
        """
        match self.__addr:
            case bytes(addr):
                return addr[1:]
            case _:
                return None

    def as_raw(self) -> str | bytes:
        """
        Returns the raw representation of this address.

        Examples:

            >>> UnixSocketAddress.from_pathname("/tmp/sock").as_raw()
            '/tmp/sock'
            >>> UnixSocketAddress.from_abstract_name(b"hidden").as_raw()
            b'\\x00hidden'
            >>> UnixSocketAddress().as_raw() # Unnamed
            ''
        """
        return self.__addr or ""


@runtime_checkable
class SupportsSocketOptions(Protocol):
    """
    Interface for an object which support getting and setting socket options.
    """

    @overload
    @abstractmethod
    def getsockopt(self, level: int, optname: int, /) -> int: ...

    @overload
    @abstractmethod
    def getsockopt(self, level: int, optname: int, buflen: int, /) -> bytes: ...

    @abstractmethod
    def getsockopt(self, *args: Any) -> int | bytes:
        """
        Similar to :meth:`socket.socket.getsockopt`.
        """
        ...

    @overload
    @abstractmethod
    def setsockopt(self, level: int, optname: int, value: int | bytes, /) -> None: ...

    @overload
    @abstractmethod
    def setsockopt(self, level: int, optname: int, value: None, optlen: int, /) -> None: ...

    @abstractmethod
    def setsockopt(self, *args: Any) -> None:
        """
        Similar to :meth:`socket.socket.setsockopt`.
        """
        ...


@runtime_checkable
class ISocket(SupportsSocketOptions, Protocol):
    """
    Interface for an object which mirrors a :class:`~socket.socket`.
    """

    @abstractmethod
    def fileno(self) -> int:
        """
        Similar to :meth:`socket.socket.fileno`.
        """
        ...

    @abstractmethod
    def get_inheritable(self) -> bool:
        """
        Similar to :meth:`socket.socket.get_inheritable`.
        """
        ...

    @abstractmethod
    def getpeername(self) -> _RetAddress:
        """
        Similar to :meth:`socket.socket.getpeername`.
        """
        ...

    @abstractmethod
    def getsockname(self) -> _RetAddress:
        """
        Similar to :meth:`socket.socket.getsockname`.
        """
        ...

    @property
    @abstractmethod
    def family(self) -> int:
        """
        Similar to :attr:`socket.socket.family`.
        """
        ...

    @property
    @abstractmethod
    def type(self) -> int:
        """
        Similar to :attr:`socket.socket.type`.
        """
        ...

    @property
    @abstractmethod
    def proto(self) -> int:
        """
        Similar to :attr:`socket.socket.proto`.
        """
        ...


@final
@runtime_final_class
class SocketProxy:
    """
    A socket-like wrapper for exposing real transport sockets.

    These objects can be safely returned by APIs like
    `client.socket`.  All potentially disruptive
    operations (like :meth:`socket.socket.close`) are banned.
    """

    __slots__ = ("__socket", "__lock_ctx", "__runner", "__weakref__")

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
        s = f"<{self.__class__.__name__} fd={fd}, family={self.family!s}, type={self.type!s}, proto={self.proto}"

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

    def __execute(self, func: Callable[_P, _T_Return], /, *args: _P.args, **kwargs: _P.kwargs) -> _T_Return:
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
    def getsockopt(self, level: int, optname: int, /) -> int: ...

    @overload
    def getsockopt(self, level: int, optname: int, buflen: int, /) -> bytes: ...

    def getsockopt(self, *args: Any) -> int | bytes:
        """
        Calls :meth:`ISocket.getsockopt <SupportsSocketOptions.getsockopt>`.
        """
        return self.__execute(self.__socket.getsockopt, *args)  # type: ignore[arg-type]

    @overload
    def setsockopt(self, level: int, optname: int, value: int | bytes, /) -> None: ...

    @overload
    def setsockopt(self, level: int, optname: int, value: None, optlen: int, /) -> None: ...

    def setsockopt(self, *args: Any) -> None:
        """
        Calls :meth:`ISocket.setsockopt <SupportsSocketOptions.setsockopt>`.
        """
        return self.__execute(self.__socket.setsockopt, *args)  # type: ignore[arg-type]

    def getpeername(self) -> _RetAddress:
        """
        Calls :meth:`ISocket.getpeername`.
        """
        return self.__execute(self.__socket.getpeername)

    def getsockname(self) -> _RetAddress:
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


class UnixCredentials(NamedTuple):
    """
    The Unix credentials tuple of the connected process.

    .. versionadded:: 1.1
    """

    pid: int | None
    """Process ID of the peer process."""

    uid: int
    """Effective user ID of the peer process."""

    gid: int
    """Effective Group ID of the peer process."""


if os.name == "nt":  # Windows
    # https://learn.microsoft.com/en-us/windows/win32/api/winsock2/ns-winsock2-linger
    # linger struct uses unsigned short ints
    _linger_struct = Struct("@HH")
else:  # Unix/macOS
    # https://manpages.debian.org/bookworm/manpages/socket.7.en.html#SO_LINGER
    # linger struct uses signed ints
    _linger_struct = Struct("@ii")


class socket_linger(NamedTuple):
    """
    The socket linger tuple returned by :func:`get_socket_linger`.
    """

    enabled: bool
    """Linger active."""

    timeout: int
    """How many seconds to linger for (if active)."""


def get_socket_linger_struct() -> Struct:
    """
    Returns a :class:`~struct.Struct` representation of the SO_LINGER structure. See :manpage:`socket(7)` for details.

    The format of the returned struct may vary depending on the operating system.
    """
    return _linger_struct


def get_socket_linger(sock: SupportsSocketOptions) -> socket_linger:
    """
    Gets socket linger.

    This is equivalent to::

        linger_struct = get_socket_linger_struct()
        (enabled, timeout) = linger_struct.unpack(sock.getsockopt(SOL_SOCKET, SO_LINGER, linger_struct.size))

    ``linger_struct`` is determined by the operating system. See :func:`get_socket_linger_struct` for details.

    See the Unix manual page :manpage:`socket(7)` for details.

    Parameters:
        sock: The socket.

    Note:
        Modern operating systems disable it by default.

    See Also:
        :func:`enable_socket_linger`

        :func:`disable_socket_linger`
    """
    enabled: int
    timeout: int
    enabled, timeout = _linger_struct.unpack(sock.getsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER, _linger_struct.size))
    return socket_linger(enabled=bool(enabled), timeout=timeout)


def enable_socket_linger(sock: SupportsSocketOptions, timeout: int) -> None:
    """
    Enables socket linger.

    This is equivalent to::

        linger_struct = get_socket_linger_struct()
        sock.setsockopt(SOL_SOCKET, SO_LINGER, linger_struct.pack(1, timeout))

    ``linger_struct`` is determined by the operating system. See :func:`get_socket_linger_struct` for details.

    See the Unix manual page :manpage:`socket(7)` for the meaning of the argument `timeout`.

    Parameters:
        sock: The socket.
        timeout: How many seconds to linger for.

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

        linger_struct = get_socket_linger_struct()
        sock.setsockopt(SOL_SOCKET, SO_LINGER, linger_struct.pack(0, 0))

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
    if wrap_in_proxy:
        sock = SocketProxy(sock)
    return {
        SocketAttribute.socket: lambda: sock,
        SocketAttribute.family: lambda: _cast_socket_family(sock.family),
        SocketAttribute.sockname: lambda: _address_or_lookup_error(sock.fileno, sock.getsockname),
        SocketAttribute.peername: lambda: _address_or_lookup_error(sock.fileno, sock.getpeername),
    }


def _get_tls_extra(ssl_object: SSLObject | SSLSocket, standard_compatible: bool) -> dict[Any, Callable[[], Any]]:
    return {
        TLSAttribute.sslcontext: lambda: ssl_object.context,
        TLSAttribute.peercert: lambda: _value_or_lookup_error(ssl_object.getpeercert()),
        TLSAttribute.cipher: lambda: _value_or_lookup_error(ssl_object.cipher()),
        TLSAttribute.compression: lambda: _value_or_lookup_error(ssl_object.compression()),
        TLSAttribute.tls_version: lambda: _value_or_lookup_error(ssl_object.version()),
        TLSAttribute.standard_compatible: lambda: standard_compatible,
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


def _address_or_lookup_error(fileno: Callable[[], int], getsockaddr: Callable[[], _T_Return]) -> _T_Return:
    try:
        if fileno() < 0:
            from errno import EBADF

            from ._errno import error_from_errno

            raise error_from_errno(EBADF)
        return getsockaddr()
    except OSError as exc:
        from ..exceptions import TypedAttributeLookupError

        raise TypedAttributeLookupError("address not available") from exc


def _value_or_lookup_error(value: _T_Return | None) -> _T_Return:
    if value is None:
        from ..exceptions import TypedAttributeLookupError

        raise TypedAttributeLookupError("value not available")
    return value
