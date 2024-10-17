from __future__ import annotations

import os
import pathlib
import socket
import sys
from collections.abc import Callable, Iterator
from errno import EBADF, EINVAL, ENOTCONN
from socket import AF_INET, AF_INET6, IPPROTO_TCP, SO_KEEPALIVE, SO_LINGER, SOL_SOCKET, TCP_NODELAY
from struct import Struct
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.socket import (
    IPv4SocketAddress,
    IPv6SocketAddress,
    SocketAddress,
    SocketProxy,
    UnixCredentials,
    UnixSocketAddress,
    _get_peer_credentials_impl_from_platform,
    disable_socket_linger,
    enable_socket_linger,
    get_socket_linger,
    get_socket_linger_struct,
    new_socket_address,
    set_tcp_keepalive,
    set_tcp_nodelay,
    socket_linger,
)

import pytest

from ...tools import PlatformMarkers
from .._utils import partial_eq, unsupported_families
from ..base import INET_FAMILIES

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestSocketAddress:
    @pytest.mark.parametrize("address", [IPv4SocketAddress("127.0.0.1", 3000), IPv6SocketAddress("127.0.0.1", 3000)])
    def test____for_connection____return_host_port_tuple(self, address: SocketAddress) -> None:
        # Arrange

        # Act
        host, port = address.for_connection()

        # Assert
        assert host is address.host
        assert port is address.port

    @pytest.mark.parametrize("address", [IPv4SocketAddress("127.0.0.1", 3000), IPv6SocketAddress("127.0.0.1", 3000)])
    def test____display____show_host_and_port(self, address: SocketAddress) -> None:
        # Arrange

        # Act
        address_as_str = str(address)

        # Assert
        assert address_as_str == f"({address.host!r}, {address.port})"

    @pytest.mark.parametrize(
        ["address", "family", "expected_type"],
        [
            pytest.param(("127.0.0.1", 3000), AF_INET, IPv4SocketAddress),
            pytest.param(("127.0.0.1", 3000), AF_INET6, IPv6SocketAddress),
            pytest.param(("127.0.0.1", 3000, 0, 0), AF_INET6, IPv6SocketAddress),
        ],
    )
    def test____new_socket_address____factory(
        self,
        address: tuple[Any, ...],
        family: int,
        expected_type: type[SocketAddress],
    ) -> None:
        # Arrange

        # Act
        socket_address = new_socket_address(address, family)

        # Assert
        assert isinstance(socket_address, expected_type)

    @pytest.mark.parametrize("socket_family_name", list(unsupported_families(INET_FAMILIES)))
    def test____new_socket_address____unsupported_family(
        self,
        socket_family_name: str,
    ) -> None:
        # Arrange
        import socket

        family: int = getattr(socket, socket_family_name)

        # Act & Assert
        with pytest.raises(ValueError, match=r"^Unsupported address family .+$"):
            _ = new_socket_address(("127.0.0.1", 12345), family)


@PlatformMarkers.skipif_platform_win32
class TestUnixSocketAddress:
    def test____dunder_init____is_unnamed_address(self) -> None:
        # Arrange

        # Act
        addr = UnixSocketAddress()

        # Assert
        assert addr.is_unnamed()
        assert addr.as_pathname() is None
        assert addr.as_abstract_name() is None
        assert addr.as_raw() == ""

    @pytest.mark.parametrize(
        "path",
        ["/path/to/sock", pathlib.Path("/path/to/sock"), pathlib.PurePath("/path/to/sock")],
        ids=repr,
    )
    def test____from_pathname____is_named_address(self, path: str | pathlib.Path | pathlib.PurePath) -> None:
        # Arrange

        # Act
        addr = UnixSocketAddress.from_pathname(path)

        # Assert
        assert not addr.is_unnamed()
        assert addr.as_pathname() == pathlib.Path("/path/to/sock")
        assert addr.as_abstract_name() is None
        assert addr.as_raw() == "/path/to/sock"

    @pytest.mark.parametrize(
        "path",
        ["/path/with/\0/bytes", pathlib.Path("/path/with/\0/bytes"), pathlib.PurePath("/path/with/\0/bytes")],
        ids=repr,
    )
    def test____from_pathname____null_byte_in_str(self, path: str | pathlib.Path | pathlib.PurePath) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^paths must not contain interior null bytes$"):
            _ = UnixSocketAddress.from_pathname(path)

    def test____from_pathname____bytes_path(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a str object or an os.PathLike object, got .+$"):
            _ = UnixSocketAddress.from_pathname(b"/path/to/sock")  # type: ignore[arg-type]

    def test____from_pathname____empty_str(self) -> None:
        # Arrange

        # Act
        addr = UnixSocketAddress.from_pathname("")

        # Assert
        assert addr.is_unnamed()
        assert addr.as_pathname() is None
        assert addr.as_abstract_name() is None
        assert addr.as_raw() == ""

    @pytest.mark.parametrize(
        "name",
        ["hidden", b"hidden"],
        ids=repr,
    )
    def test____from_abstract_name____is_in_abstract_namespace(self, name: str | bytes) -> None:
        # Arrange

        # Act
        addr = UnixSocketAddress.from_abstract_name(name)

        # Assert
        assert not addr.is_unnamed()
        assert addr.as_pathname() is None
        assert addr.as_abstract_name() == b"hidden"
        assert addr.as_raw() == b"\x00hidden"

    def test____from_abstract_name____refuse_path_like_objects(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a str object or a bytes object, got .+$"):
            _ = UnixSocketAddress.from_abstract_name(pathlib.Path("hidden"))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "path",
        ["/path/to/sock", b"/path/to/sock"],
        ids=repr,
    )
    def test____from_raw____pathname(self, path: str | bytes) -> None:
        # Arrange

        # Act
        addr = UnixSocketAddress.from_raw(path)

        # Assert
        assert not addr.is_unnamed()
        assert addr.as_pathname() == pathlib.Path("/path/to/sock")
        assert addr.as_abstract_name() is None
        assert addr.as_raw() == "/path/to/sock"

    @pytest.mark.parametrize(
        "name",
        ["\0hidden", b"\x00hidden"],
        ids=repr,
    )
    def test____from_raw____is_in_abstract_namespace(self, name: str | bytes) -> None:
        # Arrange

        # Act
        addr = UnixSocketAddress.from_raw(name)

        # Assert
        assert not addr.is_unnamed()
        assert addr.as_pathname() is None
        assert addr.as_abstract_name() == b"hidden"
        assert addr.as_raw() == b"\x00hidden"

    @pytest.mark.parametrize(
        "name",
        ["", b""],
        ids=repr,
    )
    def test____from_raw____unnamed(self, name: str | bytes) -> None:
        # Arrange

        # Act
        addr = UnixSocketAddress.from_raw(name)

        # Assert
        assert addr.is_unnamed()
        assert addr.as_pathname() is None
        assert addr.as_abstract_name() is None
        assert addr.as_raw() == ""

    def test____from_raw____invalid_object_type(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Cannot convert \('127.0.0.1', 12345\) to a UnixSocketAddress$"):
            _ = UnixSocketAddress.from_raw(("127.0.0.1", 12345))

    @pytest.mark.parametrize(
        "raw_addr",
        ["/path/to/sock", b"\0hidden", ""],
        ids=repr,
    )
    def test____uniqueness____hash_and_eq(self, raw_addr: str | bytes) -> None:
        # Arrange
        addr_1 = UnixSocketAddress.from_raw(raw_addr)
        addr_2 = UnixSocketAddress.from_raw(raw_addr)
        addr_3 = UnixSocketAddress.from_raw("/path/to/other/sock")
        assert addr_1 is not addr_2

        # Act & Assert
        assert addr_1 == addr_2
        assert hash(addr_1) == hash(addr_2)
        assert addr_1 == addr_2
        assert addr_1 != addr_3
        assert addr_2 != addr_3
        assert hash(addr_1) != hash(addr_3)
        assert hash(addr_2) != hash(addr_3)

        assert addr_1 != raw_addr
        assert addr_2 != raw_addr

    @pytest.mark.parametrize(
        "raw_addr",
        ["/path/to/sock", b"\0hidden", ""],
        ids=repr,
    )
    def test____display____show_value_and_kind(self, raw_addr: str | bytes) -> None:
        # Arrange
        address = UnixSocketAddress.from_raw(raw_addr)

        # Act
        address_as_str = str(address)

        # Assert
        if address.is_unnamed():
            assert address_as_str == "(unnamed)"
        elif (name := address.as_abstract_name()) is not None:
            assert address_as_str == f"{name!r} (abstract)"
        else:
            path = address.as_pathname()
            assert path is not None
            assert address_as_str == f"{os.fspath(path)} (pathname)"


class TestSocketProxy:
    @pytest.fixture(
        params=[
            pytest.param(False, id="without_runner"),
            pytest.param(True, id="with_runner"),
        ]
    )
    @staticmethod
    def runner_stub(request: Any, mocker: MockerFixture) -> MagicMock | None:
        use_runner: bool = request.param
        if not use_runner:
            return None

        def runner(func: Callable[[], Any]) -> Any:
            return func()

        return mocker.MagicMock(spec=runner, side_effect=runner)

    @pytest.mark.parametrize("prop", ["family", "type", "proto"])
    def test____property____access(
        self,
        prop: str,
        mock_tcp_socket: MagicMock,
        runner_stub: MagicMock | None,
    ) -> None:
        # Arrange
        expected_value = getattr(mock_tcp_socket, prop)

        # Act
        socket_proxy = SocketProxy(mock_tcp_socket, runner=runner_stub)
        prop_value = getattr(socket_proxy, prop)

        # Assert
        assert prop_value == expected_value
        if runner_stub is not None:
            runner_stub.assert_not_called()

    @pytest.mark.parametrize("family", [int(socket.AF_INET), int(9999999)])
    def test____family____cast(
        self,
        family: int,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        assert type(family) is int
        mock_tcp_socket.family = family

        # Act
        socket_proxy = SocketProxy(mock_tcp_socket)
        socket_proxy_family = socket_proxy.family

        # Assert
        try:
            family = socket.AddressFamily(family)
        except ValueError:
            assert type(socket_proxy_family) is int
            assert socket_proxy_family == family
        else:
            assert isinstance(socket_proxy_family, socket.AddressFamily)
            assert socket_proxy_family is family

    @pytest.mark.parametrize("sock_type", [int(socket.SOCK_STREAM), int(9999999)])
    def test____type____cast(
        self,
        sock_type: int,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        assert type(sock_type) is int
        mock_tcp_socket.type = sock_type

        # Act
        socket_proxy = SocketProxy(mock_tcp_socket)
        socket_proxy_type = socket_proxy.type

        # Assert
        try:
            sock_type = socket.SocketKind(sock_type)
        except ValueError:
            assert type(socket_proxy_type) is int
            assert socket_proxy_type == sock_type
        else:
            assert isinstance(socket_proxy_type, socket.SocketKind)
            assert socket_proxy_type is sock_type

    def test____fileno____sub_call(
        self,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
        runner_stub: MagicMock | None,
    ) -> None:
        # Arrange
        mock_tcp_socket.fileno.return_value = mocker.sentinel.fd
        socket_proxy = SocketProxy(mock_tcp_socket, runner=runner_stub)

        # Act
        fd = socket_proxy.fileno()

        # Assert
        mock_tcp_socket.fileno.assert_called_once_with()
        assert fd is mocker.sentinel.fd
        if runner_stub is not None:
            runner_stub.assert_called_once_with(mock_tcp_socket.fileno)

    def test____get_inheritable____sub_call(
        self,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
        runner_stub: MagicMock | None,
    ) -> None:
        # Arrange
        mock_tcp_socket.get_inheritable.return_value = mocker.sentinel.status
        socket_proxy = SocketProxy(mock_tcp_socket, runner=runner_stub)

        # Act
        status = socket_proxy.get_inheritable()

        # Assert
        mock_tcp_socket.get_inheritable.assert_called_once_with()
        assert status is mocker.sentinel.status
        if runner_stub is not None:
            runner_stub.assert_called_once_with(mock_tcp_socket.get_inheritable)

    @pytest.mark.parametrize("nb_args", [2, 3], ids=lambda nb: f"{nb} arguments")
    def test____getsockopt____sub_call(
        self,
        nb_args: int,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
        runner_stub: MagicMock | None,
    ) -> None:
        # Arrange
        mock_tcp_socket.getsockopt.return_value = mocker.sentinel.value
        socket_proxy = SocketProxy(mock_tcp_socket, runner=runner_stub)
        args: tuple[Any, ...] = (mocker.sentinel.level, mocker.sentinel.optname)
        if nb_args == 3:
            args += (mocker.sentinel.buflen,)

        # Act
        value = socket_proxy.getsockopt(*args)

        # Assert
        mock_tcp_socket.getsockopt.assert_called_once_with(*args)
        assert value is mocker.sentinel.value
        if runner_stub is not None:
            runner_stub.assert_called_once_with(partial_eq(mock_tcp_socket.getsockopt, *args))

    @pytest.mark.parametrize("nb_args", [3, 4], ids=lambda nb: f"{nb} arguments")
    def test____setsockopt____sub_call(
        self,
        nb_args: int,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
        runner_stub: MagicMock | None,
    ) -> None:
        # Arrange
        socket_proxy = SocketProxy(mock_tcp_socket, runner=runner_stub)
        args: tuple[Any, ...] = (mocker.sentinel.level, mocker.sentinel.optname, mocker.sentinel.value)
        if nb_args == 4:
            args += (mocker.sentinel.optlen,)

        # Act
        socket_proxy.setsockopt(*args)

        # Assert
        mock_tcp_socket.setsockopt.assert_called_once_with(*args)
        if runner_stub is not None:
            runner_stub.assert_called_once_with(partial_eq(mock_tcp_socket.setsockopt, *args))

    @pytest.mark.parametrize("method", ["getsockname", "getpeername"])
    def test____socket_address____sub_call(
        self,
        method: str,
        mock_tcp_socket: MagicMock,
        mocker: MockerFixture,
        runner_stub: MagicMock | None,
    ) -> None:
        # Arrange
        socket_proxy = SocketProxy(mock_tcp_socket, runner=runner_stub)
        getattr(mock_tcp_socket, method).return_value = mocker.sentinel.address

        # Act
        address = getattr(socket_proxy, method)()

        # Assert
        getattr(mock_tcp_socket, method).assert_called_once_with()
        assert address is mocker.sentinel.address
        if runner_stub is not None:
            runner_stub.assert_called_once_with(getattr(mock_tcp_socket, method))


class TestSocketOptions:
    @pytest.mark.parametrize("state", [False, True])
    def test____set_tcp_nodelay____setsockopt(
        self,
        state: bool,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        set_tcp_nodelay(mock_tcp_socket, state)

        # Assert
        mock_tcp_socket.setsockopt.assert_called_once_with(IPPROTO_TCP, TCP_NODELAY, state)

    @pytest.mark.parametrize("state", [False, True])
    def test____set_tcp_keepalive____setsockopt(
        self,
        state: bool,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange

        # Act
        set_tcp_keepalive(mock_tcp_socket, state)

        # Assert
        mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_KEEPALIVE, state)

    @pytest.mark.parametrize(
        ["enabled", "timeout"],
        [
            pytest.param(False, 0),
            pytest.param(True, 0),
            pytest.param(True, 60),
        ],
    )
    def test____get_socket_linger____getsockopt(
        self,
        mock_tcp_socket: MagicMock,
        enabled: bool,
        timeout: int,
    ) -> None:
        # Arrange
        linger_struct = get_socket_linger_struct()
        expected_buffer: bytes = linger_struct.pack(enabled, timeout)
        mock_tcp_socket.getsockopt.return_value = expected_buffer

        # Act
        linger = get_socket_linger(mock_tcp_socket)

        # Assert
        mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_LINGER, linger_struct.size)
        assert isinstance(linger, socket_linger)
        if enabled:
            assert linger.enabled is True
        else:
            assert linger.enabled is False
        assert linger.timeout == timeout

    @pytest.mark.parametrize("timeout", [0, 60])
    def test____enable_socket_linger____setsockopt(
        self,
        mock_tcp_socket: MagicMock,
        timeout: int,
    ) -> None:
        # Arrange
        linger_struct = get_socket_linger_struct()
        expected_buffer: bytes = linger_struct.pack(1, timeout)  # Enabled with timeout

        # Act
        enable_socket_linger(mock_tcp_socket, timeout)

        # Assert
        mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_LINGER, expected_buffer)

    def test____disable_socket_linger____setsockopt(
        self,
        mock_tcp_socket: MagicMock,
    ) -> None:
        # Arrange
        linger_struct = get_socket_linger_struct()
        expected_buffer: bytes = linger_struct.pack(0, 0)

        # Act
        disable_socket_linger(mock_tcp_socket)

        # Assert
        mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_LINGER, expected_buffer)


class TestSocketPeerCredentials:
    WINDOWS = ("win32", "cygwin")
    LINUX = ("linux",)
    MACOS = ("darwin",)
    FREEBSD = ("freebsdXX",)
    OPENBSD = ("openbsdXX",)
    NETBSD = ("netbsdXX",)
    DRAGONFLYBSD = ("dragonflyXX",)

    @pytest.fixture(scope="class", autouse=True)
    @staticmethod
    def clear_cache_at_end() -> Iterator[None]:
        yield
        _get_peer_credentials_impl_from_platform.cache_clear()

    @pytest.fixture(autouse=True)
    @staticmethod
    def clear_cache_before_proceed() -> None:
        _get_peer_credentials_impl_from_platform.cache_clear()

    @pytest.fixture(autouse=True)
    @staticmethod
    def AF_UNIX(monkeypatch: pytest.MonkeyPatch) -> int:
        AF_UNIX: int = 1
        monkeypatch.setattr("socket.AF_UNIX", AF_UNIX, raising=False)
        return AF_UNIX

    @pytest.fixture(autouse=True)
    @staticmethod
    def SO_PEERCRED(monkeypatch: pytest.MonkeyPatch) -> int:
        SO_PEERCRED: int = 17
        monkeypatch.setattr("socket.SO_PEERCRED", SO_PEERCRED, raising=False)
        return SO_PEERCRED

    @pytest.fixture(autouse=True)
    @staticmethod
    def platform(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
        if hasattr(request, "param"):
            monkeypatch.setattr(sys, "platform", request.param)
            assert sys.platform == request.param
        return sys.platform

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_find_library(platform: str, mocker: MockerFixture) -> MagicMock:
        match platform:
            case "darwin":
                return mocker.patch("ctypes.util.find_library", side_effect=lambda lib: f"/path/to/lib{lib}.dylib")
            case _:
                return mocker.patch("ctypes.util.find_library", side_effect=lambda lib: f"/path/to/lib{lib}.so")

    @pytest.fixture
    @staticmethod
    def mock_shared_lib(mocker: MockerFixture) -> MagicMock:
        return mocker.NonCallableMagicMock()

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_CDLL(mock_shared_lib: MagicMock, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("ctypes.CDLL", return_value=mock_shared_lib)

    @pytest.fixture
    @staticmethod
    def linux_ucred_struct() -> Struct:
        return Struct("@iII")

    @pytest.fixture
    @staticmethod
    def openbsd_ucred_struct() -> Struct:
        return Struct("@IIi")

    def test____socket_ucred___field_order(self) -> None:
        # Arrange

        # Act
        ucred = UnixCredentials(12345, 1001, 1002)

        # Assert
        assert ucred.pid == 12345
        assert ucred.uid == 1001
        assert ucred.gid == 1002

    @pytest.mark.parametrize("platform", WINDOWS, indirect=True)
    def test____get_peer_credentials_impl_from_platform____not_implemented(
        self,
        platform: str,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(NotImplementedError, match=r"^There is no implementation available for '%s'$" % platform):
            _get_peer_credentials_impl_from_platform()

    @pytest.mark.parametrize("platform", LINUX + OPENBSD + NETBSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____ucred_impl(
        self,
        platform: str,
        mock_unix_stream_socket: MagicMock,
        linux_ucred_struct: Struct,
        openbsd_ucred_struct: Struct,
        SO_PEERCRED: int,
    ) -> None:
        # Arrange
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        if platform in self.OPENBSD:
            expected_getsockopt_size = openbsd_ucred_struct.size
            mock_unix_stream_socket.getsockopt.return_value = openbsd_ucred_struct.pack(1001, 1002, 12345)
        else:
            expected_getsockopt_size = linux_ucred_struct.size
            mock_unix_stream_socket.getsockopt.return_value = linux_ucred_struct.pack(12345, 1001, 1002)

        # Act
        peer_creds = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert peer_creds.pid == 12345
        assert peer_creds.uid == 1001
        assert peer_creds.gid == 1002
        if platform in self.NETBSD:
            # SOL_LOCAL=0, LOCAL_PEEREID=3
            mock_unix_stream_socket.getsockopt.assert_called_once_with(0, 3, expected_getsockopt_size)
        else:
            mock_unix_stream_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_PEERCRED, expected_getsockopt_size)

    @pytest.mark.parametrize("platform", LINUX + OPENBSD + NETBSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____ucred_impl____socket_closed(
        self,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_unix_stream_socket.close()

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert exc_info.value.errno == EBADF
        mock_unix_stream_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("platform", LINUX + OPENBSD + NETBSD, indirect=True)
    @pytest.mark.parametrize("invalid_pid", [None, 0], ids=lambda p: f"invalid_pid=={p}")
    @pytest.mark.parametrize("invalid_uid", [None, -1], ids=lambda p: f"invalid_uid=={p}")
    @pytest.mark.parametrize("invalid_gid", [None, -1], ids=lambda p: f"invalid_gid=={p}")
    def test____get_peer_credentials_impl_from_platform____ucred_impl____corrupted_result(
        self,
        invalid_pid: int | None,
        invalid_uid: int | None,
        invalid_gid: int | None,
        platform: str,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        if invalid_pid is None and invalid_uid is None and invalid_pid is None:
            pytest.skip("Combination give a valid ucred")
        pid = 12345 if invalid_pid is None else invalid_pid
        uid = 1001 if invalid_uid is None else invalid_uid
        gid = 1002 if invalid_gid is None else invalid_gid
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        if platform in self.OPENBSD:
            mock_unix_stream_socket.getsockopt.return_value = Struct("3i").pack(uid, gid, pid)
        else:
            mock_unix_stream_socket.getsockopt.return_value = Struct("3i").pack(pid, uid, gid)

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert exc_info.value.errno == EINVAL

    @pytest.mark.parametrize("platform", MACOS, indirect=True)
    def test____get_peer_credentials_impl_from_platform____get_peer_eid_impl____macos_impl(
        self,
        mock_find_library: MagicMock,
        mock_shared_lib: MagicMock,
        mock_CDLL: MagicMock,
        mock_unix_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_find_library.assert_called_once_with("c")
        mock_CDLL.assert_called_once_with("/path/to/libc.dylib", use_errno=True)

        def getpeereid(fileno: Any, uid_ptr: Any, gid_ptr: Any, /) -> int:
            uid_ptr._obj.value = 1001
            gid_ptr._obj.value = 1002
            return 0

        mock_shared_lib.getpeereid.side_effect = getpeereid

        mock_unix_stream_socket.getsockopt.return_value = 12345

        # Act
        peer_creds = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert peer_creds.pid == 12345
        assert peer_creds.uid == 1001
        assert peer_creds.gid == 1002
        mock_shared_lib.getpeereid.assert_called_once_with(mock_unix_stream_socket.fileno(), mocker.ANY, mocker.ANY)
        mock_unix_stream_socket.getsockopt.assert_called_once_with(0, 2)  # SOL_LOCAL=0, LOCAL_PEERPID=2

    @pytest.mark.parametrize("platform", MACOS, indirect=True)
    def test____get_peer_credentials_impl_from_platform____get_peer_eid_impl____macos_impl____socket_closed(
        self,
        mock_find_library: MagicMock,
        mock_shared_lib: MagicMock,
        mock_CDLL: MagicMock,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_find_library.assert_called_once_with("c")
        mock_CDLL.assert_called_once_with("/path/to/libc.dylib", use_errno=True)
        mock_unix_stream_socket.close()

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert exc_info.value.errno == EBADF
        mock_shared_lib.getpeereid.assert_not_called()
        mock_unix_stream_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("platform", MACOS, indirect=True)
    def test____get_peer_credentials_impl_from_platform____get_peer_eid_impl____macos_impl____getpeereid_failed(
        self,
        mock_find_library: MagicMock,
        mock_shared_lib: MagicMock,
        mock_CDLL: MagicMock,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        import ctypes

        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_find_library.assert_called_once_with("c")
        mock_CDLL.assert_called_once_with("/path/to/libc.dylib", use_errno=True)

        def getpeereid(fileno: Any, uid_ptr: Any, gid_ptr: Any, /) -> int:
            ctypes.set_errno(ENOTCONN)
            return -1

        mock_shared_lib.getpeereid.side_effect = getpeereid

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert exc_info.value.errno == ENOTCONN
        mock_shared_lib.getpeereid.asset_called_once()
        mock_unix_stream_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("platform", MACOS, indirect=True)
    def test____get_peer_credentials_impl_from_platform____get_peer_eid_impl____macos_impl____libc_not_found(
        self,
        platform: str,
        mock_find_library: MagicMock,
        mock_CDLL: MagicMock,
    ) -> None:
        # Arrange
        mock_find_library.side_effect = [None]

        # Act
        with pytest.raises(NotImplementedError, match=r"^Could not find libc on '%s'$" % platform):
            _ = _get_peer_credentials_impl_from_platform()

        # Assert
        mock_CDLL.assert_not_called()

    @pytest.mark.parametrize("platform", FREEBSD + DRAGONFLYBSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____get_peer_eid_impl____bsd_generic_impl(
        self,
        mock_find_library: MagicMock,
        mock_shared_lib: MagicMock,
        mock_CDLL: MagicMock,
        mock_unix_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_find_library.assert_called_once_with("c")
        mock_CDLL.assert_called_once_with("/path/to/libc.so", use_errno=True)

        def getpeereid(fileno: Any, uid_ptr: Any, gid_ptr: Any, /) -> int:
            uid_ptr._obj.value = 1001
            gid_ptr._obj.value = 1002
            return 0

        mock_shared_lib.getpeereid.side_effect = getpeereid

        # Act
        peer_creds = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert peer_creds.pid is None
        assert peer_creds.uid == 1001
        assert peer_creds.gid == 1002
        mock_shared_lib.getpeereid.assert_called_once_with(mock_unix_stream_socket.fileno(), mocker.ANY, mocker.ANY)
        mock_unix_stream_socket.getsockopt.asset_not_called()

    @pytest.mark.parametrize("platform", FREEBSD + DRAGONFLYBSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____get_peer_eid_impl____bsd_generic_impl____socket_closed(
        self,
        mock_find_library: MagicMock,
        mock_shared_lib: MagicMock,
        mock_CDLL: MagicMock,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_find_library.assert_called_once_with("c")
        mock_CDLL.assert_called_once_with("/path/to/libc.so", use_errno=True)
        mock_unix_stream_socket.close()

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert exc_info.value.errno == EBADF
        mock_shared_lib.getpeereid.assert_not_called()
        mock_unix_stream_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("platform", FREEBSD + DRAGONFLYBSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____get_peer_eid_impl____bsd_generic_impl____getpeereid_failed(
        self,
        mock_find_library: MagicMock,
        mock_shared_lib: MagicMock,
        mock_CDLL: MagicMock,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        import ctypes

        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_find_library.assert_called_once_with("c")
        mock_CDLL.assert_called_once_with("/path/to/libc.so", use_errno=True)

        def getpeereid(fileno: Any, uid_ptr: Any, gid_ptr: Any, /) -> int:
            ctypes.set_errno(ENOTCONN)
            return -1

        mock_shared_lib.getpeereid.side_effect = getpeereid

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert exc_info.value.errno == ENOTCONN
        mock_shared_lib.getpeereid.asset_called_once()
        mock_unix_stream_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("platform", FREEBSD + DRAGONFLYBSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____get_peer_eid_impl____bsd_generic_impl____libc_not_found(
        self,
        platform: str,
        mock_find_library: MagicMock,
        mock_CDLL: MagicMock,
    ) -> None:
        # Arrange
        mock_find_library.side_effect = [None]

        # Act
        with pytest.raises(NotImplementedError, match=r"^Could not find libc on '%s'$" % platform):
            _ = _get_peer_credentials_impl_from_platform()

        # Assert
        mock_CDLL.assert_not_called()
