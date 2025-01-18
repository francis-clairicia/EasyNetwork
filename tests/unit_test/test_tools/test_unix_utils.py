from __future__ import annotations

import pathlib
import sys
from collections.abc import Callable, Iterator
from errno import EBADF, EINVAL, ENOTCONN
from socket import SOL_SOCKET
from struct import Struct
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._unix_utils import (
    UnixCredsContainer,
    _get_peer_credentials_impl_from_platform,
    check_unix_socket_family,
    convert_optional_unix_socket_address,
    convert_unix_socket_address,
    is_unix_socket_family,
    platform_supports_automatic_socket_bind,
)
from easynetwork.lowlevel.socket import UnixCredentials, UnixSocketAddress

import pytest

from tests.tools import PlatformMarkers

from ...fixtures.socket import socket_family_or_skip
from .._utils import unsupported_families
from ..base import UNIX_FAMILIES

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture(params=list(UNIX_FAMILIES))
def socket_family(request: pytest.FixtureRequest) -> Any:
    return socket_family_or_skip(request.param)


@pytest.mark.parametrize("socket_family", list(UNIX_FAMILIES), indirect=True)
def test____check_unix_socket_family____valid_family(socket_family: int) -> None:
    # Arrange

    # Act
    check_unix_socket_family(socket_family)

    # Assert
    ## There is no exception


@pytest.mark.parametrize("socket_family", list(unsupported_families(UNIX_FAMILIES)), indirect=True)
def test____check_unix_socket_family____invalid_family(socket_family: int) -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(ValueError, match=r"^Only these families are supported: AF_UNIX$"):
        check_unix_socket_family(socket_family)


def test____is_unix_socket_family____AF_UNIX_defined(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    import socket
    from enum import IntEnum

    class AddressFamily(IntEnum):
        AF_UNIX = 1
        AF_INET = 2
        AF_INET6 = 10

    monkeypatch.setattr("socket.AddressFamily", AddressFamily)
    monkeypatch.setattr("socket.AF_UNIX", AddressFamily.AF_UNIX, raising=False)
    monkeypatch.setattr("socket.AF_INET", AddressFamily.AF_INET)
    monkeypatch.setattr("socket.AF_INET6", AddressFamily.AF_INET6)

    # Act & Assert
    assert is_unix_socket_family(getattr(socket, "AF_UNIX"))
    assert not is_unix_socket_family(socket.AF_INET)
    assert not is_unix_socket_family(socket.AF_INET6)


def test____is_unix_socket_family____AF_UNIX_undefined(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    import socket
    from enum import IntEnum

    class AddressFamily(IntEnum):
        AF_INET = 2
        AF_INET6 = 10

    monkeypatch.setattr("socket.AddressFamily", AddressFamily)
    monkeypatch.delattr("socket.AF_UNIX", raising=False)
    monkeypatch.setattr("socket.AF_INET", AddressFamily.AF_INET)
    monkeypatch.setattr("socket.AF_INET6", AddressFamily.AF_INET6)

    # Act & Assert
    assert not is_unix_socket_family(socket.AF_INET)
    assert not is_unix_socket_family(socket.AF_INET6)


@pytest.mark.parametrize(
    ["input", "expected_output"],
    [
        pytest.param("/path/to/sock", "/path/to/sock"),
        pytest.param(pathlib.Path("/path/to/sock"), "/path/to/sock"),
        pytest.param(UnixSocketAddress.from_pathname("/path/to/sock"), "/path/to/sock"),
        pytest.param(b"\0abstract", b"\0abstract"),
        pytest.param(UnixSocketAddress.from_abstract_name(b"abstract"), b"\0abstract"),
        pytest.param("", ""),
        pytest.param(UnixSocketAddress(), ""),
    ],
)
@pytest.mark.parametrize("conversion_func", [convert_unix_socket_address, convert_optional_unix_socket_address])
@PlatformMarkers.skipif_platform_win32
def test_____convert_unix_socket_address____transform_to_raw_address(
    input: str | pathlib.Path | bytes | UnixSocketAddress,
    expected_output: str | bytes,
    conversion_func: Callable[[str | pathlib.Path | bytes | UnixSocketAddress], str | bytes],
) -> None:
    # Arrange

    # Act
    output = conversion_func(input)

    # Assert
    assert type(output) is type(expected_output)
    assert output == expected_output


@PlatformMarkers.skipif_platform_win32
def test_____convert_optional_unix_socket_address____skip_None() -> None:
    # Arrange

    # Act
    output = convert_optional_unix_socket_address(None)

    # Assert
    assert output is None


@pytest.mark.parametrize("platform", ["linux"])
def test____platform_supports_automatic_socket_bind____supported(platform: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr("sys.platform", platform)

    # Act & Assert
    assert platform_supports_automatic_socket_bind()


@pytest.mark.parametrize("platform", ["darwin", "freebsdXX", "openbsdXX", "netbsdXX", "dragonflyXX"])
def test____platform_supports_automatic_socket_bind_____not_supported(platform: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr("sys.platform", platform)

    # Act & Assert
    assert not platform_supports_automatic_socket_bind()


class TestLazyPeerCredsContainer:
    @pytest.fixture
    @staticmethod
    def mock_get_peer_credentials(mock_get_peer_credentials: MagicMock) -> MagicMock:
        mock_get_peer_credentials.return_value = UnixCredentials(12345, 1001, 1001)
        return mock_get_peer_credentials

    def test____get____compute_credentials(
        self,
        mock_unix_stream_socket: MagicMock,
        mock_get_peer_credentials: MagicMock,
    ) -> None:
        # Arrange
        peer_creds_container = UnixCredsContainer(mock_unix_stream_socket)

        # Act
        peer_creds = peer_creds_container.get()

        # Assert
        assert peer_creds.pid == 12345
        assert peer_creds.uid == 1001
        assert peer_creds.gid == 1001
        mock_get_peer_credentials.assert_called_once_with(mock_unix_stream_socket)

    def test____get____cache_value(
        self,
        mock_unix_stream_socket: MagicMock,
        mock_get_peer_credentials: MagicMock,
    ) -> None:
        # Arrange
        peer_creds_container = UnixCredsContainer(mock_unix_stream_socket)
        cached_peer_creds = peer_creds_container.get()
        mock_get_peer_credentials.reset_mock()

        # Act
        peer_creds_1 = peer_creds_container.get()
        peer_creds_2 = peer_creds_container.get()
        peer_creds_3 = peer_creds_container.get()

        # Assert
        assert peer_creds_1 is peer_creds_2 is peer_creds_3 is cached_peer_creds
        mock_get_peer_credentials.assert_not_called()


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
