from __future__ import annotations

import os
import pathlib
import socket
import struct
import sys
from collections.abc import Callable
from socket import AF_INET, AF_INET6, IPPROTO_TCP, SO_KEEPALIVE, SO_LINGER, SOL_SOCKET, TCP_NODELAY
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.socket import (
    IPv4SocketAddress,
    IPv6SocketAddress,
    SocketAddress,
    SocketProxy,
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


if sys.platform != "win32":
    from easynetwork.lowlevel.socket import UnixSocketAddress

    class TestUnixSocketAddress:
        def test____dunder_init____is_unnamed_address(self) -> None:
            # Arrange

            # Act
            addr = UnixSocketAddress()

            # Assert
            assert addr.is_unnamed()
            assert addr.as_pathname() is None
            if sys.platform == "linux":
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
            if sys.platform == "linux":
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
            if sys.platform == "linux":
                assert addr.as_abstract_name() is None
            assert addr.as_raw() == ""

        if sys.platform == "linux":

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
            if sys.platform == "linux":
                assert addr.as_abstract_name() is None
            assert addr.as_raw() == "/path/to/sock"

        if sys.platform == "linux":

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
            if sys.platform == "linux":
                assert addr.as_abstract_name() is None
            assert addr.as_raw() == ""

        def test____from_raw____invalid_object_type(self) -> None:
            # Arrange

            # Act & Assert
            with pytest.raises(TypeError, match=r"^Cannot convert \('127.0.0.1', 12345\) to a UnixSocketAddress$"):
                _ = UnixSocketAddress.from_raw(("127.0.0.1", 12345))

        @pytest.mark.parametrize(
            "path",
            [
                "/path/with/\0/bytes",
                pathlib.Path("/path/with/\0/bytes"),
                pathlib.PurePath("/path/with/\0/bytes"),
                pytest.param("\0/path/with/nul/bytes", marks=[PlatformMarkers.abstract_sockets_unsupported]),
            ],
            ids=repr,
        )
        def test____from_raw____null_byte_in_str(self, path: str | pathlib.Path | pathlib.PurePath) -> None:
            # Arrange

            # Act & Assert
            with pytest.raises(ValueError, match=r"^paths must not contain interior null bytes$"):
                _ = UnixSocketAddress.from_pathname(path)

        @pytest.mark.parametrize(
            "raw_addr",
            [
                "/path/to/sock",
                pytest.param(b"\0hidden", marks=[PlatformMarkers.supports_abstract_sockets]),
                "",
            ],
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
            [
                "/path/to/sock",
                pytest.param(b"\0hidden", marks=[PlatformMarkers.supports_abstract_sockets]),
                "",
            ],
            ids=repr,
        )
        def test____display____show_value_in_proc_net_unix_form(self, raw_addr: str | bytes) -> None:
            # Arrange
            address = UnixSocketAddress.from_raw(raw_addr)

            # Act
            address_as_str = str(address)

            # Assert
            if address.is_unnamed():
                assert address_as_str == "<unnamed>"
            elif sys.platform == "linux" and (name := address.as_abstract_name()) is not None:
                assert address_as_str == f"@{os.fsdecode(name)}"
            else:
                path = address.as_pathname()
                assert path is not None
                assert address_as_str == os.fspath(path)


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


if sys.platform != "win32":
    from socket import SCM_RIGHTS

    from easynetwork.lowlevel.socket import SocketAncillary, UnixCredentials

    class TestSocketAncillary:
        @pytest.fixture(scope="class")
        @staticmethod
        def SCM_CREDENTIALS() -> int:
            if sys.platform.startswith("freebsd"):
                return getattr(socket, "SCM_CREDS2")
            if sys.platform.startswith("netbsd"):
                return getattr(socket, "SCM_CREDS")
            if sys.platform == "linux":
                return socket.SCM_CREDENTIALS
            pytest.skip("Cannot send unix credentials.")

        def test____add_fds____default(self) -> None:
            # Arrange
            ancdata = SocketAncillary()

            # Act
            ancdata.add_fds([3, 4, 5, 10])

            # Assert
            assert ancdata.as_raw() == [(SOL_SOCKET, SCM_RIGHTS, struct.pack("4i", 3, 4, 5, 10))]

        def test____add_fds____always_append_to_the_same_message(self) -> None:
            # Arrange
            ancdata = SocketAncillary()
            ancdata.add_fds([3, 4])

            # Act
            ancdata.add_fds([5, 10])

            # Assert
            assert ancdata.as_raw() == [(SOL_SOCKET, SCM_RIGHTS, struct.pack("4i", 3, 4, 5, 10))]

        def test____add_fds____empty_iterable(self) -> None:
            # Arrange
            ancdata = SocketAncillary()

            # Act
            ancdata.add_fds(iter([]))

            # Assert
            assert ancdata.as_raw() == []

        if sys.platform != "darwin":

            def test____add_creds____default(self, SCM_CREDENTIALS: int) -> None:
                # Arrange
                ancdata = SocketAncillary()

                # Act
                ancdata.add_creds([UnixCredentials(pid=12345, uid=1001, gid=2002)])

                # Assert
                assert ancdata.as_raw() == [(SOL_SOCKET, SCM_CREDENTIALS, struct.pack("3i", 12345, 1001, 2002))]

            def test____add_creds____empty_iterable(self) -> None:
                # Arrange
                ancdata = SocketAncillary()

                # Act
                ancdata.add_creds(iter([]))

                # Assert
                assert ancdata.as_raw() == []

        @pytest.mark.parametrize(
            ["cmsg_level_name", "cmsg_type_name", "cmsg_data"],
            [
                pytest.param("SOL_SOCKET", "SCM_RIGHTS", struct.pack("4i", 3, 4, 5, 10), id="SCM_RIGHTS"),
                pytest.param("SOL_SOCKET", "SCM_CREDENTIALS", struct.pack("3i", 12345, 1001, 2002), id="SCM_CREDENTIALS"),
            ],
        )
        def test____update_from_raw____recognized_messages(
            self,
            request: pytest.FixtureRequest,
            cmsg_level_name: str,
            cmsg_type_name: str,
            cmsg_data: bytes,
        ) -> None:
            # Arrange
            ancdata = SocketAncillary()
            cmsg_level: int = getattr(socket, cmsg_level_name)
            cmsg_type: int
            match cmsg_type_name:
                case "SCM_CREDENTIALS":
                    cmsg_type = request.getfixturevalue("SCM_CREDENTIALS")
                case _:
                    cmsg_type = getattr(socket, cmsg_type_name)

            # Act
            ancdata.update_from_raw([(cmsg_level, cmsg_type, cmsg_data)])

            # Assert
            assert ancdata.as_raw() == [(cmsg_level, cmsg_type, cmsg_data)]

        def test____update_from_raw____merge_common_messages(self) -> None:
            # Arrange
            ancdata = SocketAncillary()

            # Act
            ancdata.update_from_raw(
                [
                    (SOL_SOCKET, SCM_RIGHTS, struct.pack("i", 3)),
                    (SOL_SOCKET, SCM_RIGHTS, struct.pack("i", 4)),
                ]
            )
            ancdata.update_from_raw([(SOL_SOCKET, SCM_RIGHTS, struct.pack("2i", 5, 10))])

            # Assert
            assert ancdata.as_raw() == [(SOL_SOCKET, SCM_RIGHTS, struct.pack("4i", 3, 4, 5, 10))]

        def test____update_from_raw____raise_error_after_all_messages_has_been_parsed(self) -> None:
            # Arrange
            ancdata = SocketAncillary()

            # Act & Assert
            with pytest.RaisesGroup(pytest.RaisesExc(ValueError, match=r"Unknown message level/type pair: \(-42, -999\)")):
                ancdata.update_from_raw(
                    [
                        (-42, -999, b"unknown_message_type"),
                        (SOL_SOCKET, SCM_RIGHTS, struct.pack("4i", 3, 4, 5, 10)),
                    ]
                )
            assert ancdata.as_raw() == [(SOL_SOCKET, SCM_RIGHTS, struct.pack("4i", 3, 4, 5, 10))]

        def test____update_from_raw____handle_truncated_data____scm_rights(self) -> None:
            # Arrange
            ancdata = SocketAncillary()

            # Act
            ancdata.update_from_raw([(SOL_SOCKET, SCM_RIGHTS, struct.pack("i", 3)[:-2])])

            # Assert
            assert ancdata.as_raw() == [(SOL_SOCKET, SCM_RIGHTS, b"")]

        if sys.platform != "darwin":

            def test____update_from_raw____handle_truncated_data____scm_credentials(self, SCM_CREDENTIALS: int) -> None:
                # Arrange
                ancdata = SocketAncillary()

                # Act
                ancdata.update_from_raw([(SOL_SOCKET, SCM_CREDENTIALS, struct.pack("3i", 12345, 1001, 2002)[:-2])])

                # Assert
                assert ancdata.as_raw() == [(SOL_SOCKET, SCM_CREDENTIALS, b"")]

        def test____messages____scm_rights(self) -> None:
            # Arrange
            from easynetwork.lowlevel.socket import SCMRights

            ancdata = SocketAncillary()
            ancdata.update_from_raw([(SOL_SOCKET, SCM_RIGHTS, struct.pack("4i", 3, 4, 5, 10))])

            # Act
            fds: list[int] = []
            for messages in ancdata.messages():
                if isinstance(messages, SCMRights):
                    fds.extend(messages.fds)

            # Assert
            assert fds == [3, 4, 5, 10]

        if sys.platform != "darwin":

            def test____messages____scm_credentials(self, SCM_CREDENTIALS: int) -> None:
                # Arrange
                from easynetwork.lowlevel.socket import SCMCredentials

                ancdata = SocketAncillary()
                ancdata.update_from_raw([(SOL_SOCKET, SCM_CREDENTIALS, struct.pack("3i", 12345, 1001, 2002))])

                # Act
                unix_creds: list[UnixCredentials] = []
                for messages in ancdata.messages():
                    if isinstance(messages, SCMCredentials):
                        unix_creds.extend(messages.credentials)

                # Assert
                assert unix_creds == [UnixCredentials(pid=12345, uid=1001, gid=2002)]

        def test____clear____default(self) -> None:
            # Arrange
            ancdata = SocketAncillary()
            ancdata.update_from_raw([(SOL_SOCKET, SCM_RIGHTS, struct.pack("4i", 3, 4, 5, 10))])
            assert len(ancdata.as_raw()) > 0

            # Act
            ancdata.clear()

            # Assert
            assert ancdata.as_raw() == []
