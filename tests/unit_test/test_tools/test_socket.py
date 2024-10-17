from __future__ import annotations

import socket
import sys
from collections.abc import Callable, Iterator
from errno import EBADF, ENOTCONN
from socket import AF_INET, AF_INET6, IPPROTO_TCP, SO_KEEPALIVE, SO_LINGER, SOL_SOCKET, TCP_NODELAY
from struct import Struct
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.socket import (
    IPv4SocketAddress,
    IPv6SocketAddress,
    SocketAddress,
    SocketProxy,
    _get_peer_credentials_impl_from_platform,
    disable_socket_linger,
    enable_socket_linger,
    get_socket_linger,
    get_socket_linger_struct,
    new_socket_address,
    set_tcp_keepalive,
    set_tcp_nodelay,
    socket_linger,
    socket_ucred,
)

import pytest

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
    BSD = ("freebsdXX", "openbsdXX", "netbsdXX", "dragonflyXX")

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

    def test____socket_ucred___field_order(self) -> None:
        # Arrange

        # Act
        ucred = socket_ucred(12345, 1001, 1002)

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

    @pytest.mark.parametrize("platform", LINUX, indirect=True)
    def test____get_peer_credentials_impl_from_platform____linux_impl(
        self,
        mock_unix_stream_socket: MagicMock,
        linux_ucred_struct: Struct,
        SO_PEERCRED: int,
    ) -> None:
        # Arrange
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_unix_stream_socket.getsockopt.return_value = linux_ucred_struct.pack(12345, 1001, 1002)

        # Act
        peer_creds = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert peer_creds.pid == 12345
        assert peer_creds.uid == 1001
        assert peer_creds.gid == 1002
        mock_unix_stream_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_PEERCRED, linux_ucred_struct.size)

    @pytest.mark.parametrize("platform", LINUX, indirect=True)
    def test____get_peer_credentials_impl_from_platform____linux_impl____socket_closed(
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

    @pytest.mark.parametrize("platform", MACOS, indirect=True)
    def test____get_peer_credentials_impl_from_platform____macos_impl(
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
    def test____get_peer_credentials_impl_from_platform____macos_impl____socket_closed(
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
    def test____get_peer_credentials_impl_from_platform____macos_impl____getpeereid_failed(
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
    def test____get_peer_credentials_impl_from_platform____macos_impl____libc_not_found(
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

    @pytest.mark.parametrize("platform", BSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____bsd_impl(
        self,
        mock_find_library: MagicMock,
        mock_shared_lib: MagicMock,
        mock_CDLL: MagicMock,
        mock_unix_stream_socket: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_find_library.assert_called_once_with("bsd")
        mock_CDLL.assert_called_once_with("/path/to/libbsd.so", use_errno=True)

        def getpeereid(fileno: Any, uid_ptr: Any, gid_ptr: Any, /) -> int:
            uid_ptr._obj.value = 1001
            gid_ptr._obj.value = 1002
            return 0

        mock_shared_lib.getpeereid.side_effect = getpeereid

        # Act
        peer_creds = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert peer_creds.pid == -1
        assert peer_creds.uid == 1001
        assert peer_creds.gid == 1002
        mock_shared_lib.getpeereid.assert_called_once_with(mock_unix_stream_socket.fileno(), mocker.ANY, mocker.ANY)
        mock_unix_stream_socket.getsockopt.asset_not_called()

    @pytest.mark.parametrize("platform", BSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____bsd_impl____socket_closed(
        self,
        mock_find_library: MagicMock,
        mock_shared_lib: MagicMock,
        mock_CDLL: MagicMock,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_find_library.assert_called_once_with("bsd")
        mock_CDLL.assert_called_once_with("/path/to/libbsd.so", use_errno=True)
        mock_unix_stream_socket.close()

        # Act
        with pytest.raises(OSError) as exc_info:
            _ = get_peer_credentials(mock_unix_stream_socket)

        # Assert
        assert exc_info.value.errno == EBADF
        mock_shared_lib.getpeereid.assert_not_called()
        mock_unix_stream_socket.getsockopt.assert_not_called()

    @pytest.mark.parametrize("platform", BSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____bsd_impl____getpeereid_failed(
        self,
        mock_find_library: MagicMock,
        mock_shared_lib: MagicMock,
        mock_CDLL: MagicMock,
        mock_unix_stream_socket: MagicMock,
    ) -> None:
        # Arrange
        import ctypes

        get_peer_credentials = _get_peer_credentials_impl_from_platform()
        mock_find_library.assert_called_once_with("bsd")
        mock_CDLL.assert_called_once_with("/path/to/libbsd.so", use_errno=True)

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

    @pytest.mark.parametrize("platform", BSD, indirect=True)
    def test____get_peer_credentials_impl_from_platform____bsd_impl____libbsd_not_found(
        self,
        platform: str,
        mock_find_library: MagicMock,
        mock_CDLL: MagicMock,
    ) -> None:
        # Arrange
        mock_find_library.side_effect = [None]

        # Act
        with pytest.raises(NotImplementedError, match=r"^Could not find libbsd on '%s'$" % platform):
            _ = _get_peer_credentials_impl_from_platform()

        # Assert
        mock_CDLL.assert_not_called()
