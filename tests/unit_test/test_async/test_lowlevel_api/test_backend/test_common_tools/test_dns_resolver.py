from __future__ import annotations

import asyncio
import asyncio.trsock
import errno
from collections.abc import Callable, Sequence
from socket import (
    AF_INET,
    AF_INET6,
    AF_UNSPEC,
    AI_ADDRCONFIG,
    AI_NUMERICHOST,
    AI_NUMERICSERV,
    AI_PASSIVE,
    EAI_BADFLAGS,
    EAI_NONAME,
    IPPROTO_TCP,
    IPPROTO_UDP,
    SOCK_DGRAM,
    SOCK_STREAM,
    SocketType,
    gaierror,
)
from typing import TYPE_CHECKING, Any, Literal, Protocol as TypingProtocol, assert_never

from easynetwork.lowlevel._utils import error_from_errno
from easynetwork.lowlevel.api_async.backend._asyncio.tasks import TaskUtils
from easynetwork.lowlevel.api_async.backend._common.dns_resolver import BaseAsyncDNSResolver
from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend

import pytest

from ......fixtures.socket import socket_family_or_skip
from ......tools import PlatformMarkers
from ....._utils import datagram_addrinfo_list, stream_addrinfo_list, unsupported_families
from .....base import INET_FAMILIES

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


class MockedDNSResolver(BaseAsyncDNSResolver):
    def __init__(self, event_loop: asyncio.AbstractEventLoop, mocker: MockerFixture) -> None:
        self.mock_async_getaddrinfo: AsyncMock = mocker.patch.object(event_loop, "getaddrinfo", new_callable=mocker.AsyncMock)
        self.mock_sock_connect: AsyncMock = mocker.AsyncMock(return_value=None)

    async def connect_socket(self, socket: SocketType, address: tuple[str, int] | tuple[str, int, int, int]) -> None:
        return await self.mock_sock_connect(socket, address)


@pytest.fixture
def dns_resolver(event_loop: asyncio.AbstractEventLoop, mocker: MockerFixture) -> MockedDNSResolver:
    return MockedDNSResolver(event_loop, mocker)


@pytest.fixture(autouse=True)
def mock_stdlib_socket_getaddrinfo(mocker: MockerFixture) -> MagicMock:
    from socket import EAI_NONAME, gaierror

    return mocker.patch("socket.getaddrinfo", autospec=True, side_effect=gaierror(EAI_NONAME, "Name or service not known"))


@pytest.fixture
def mock_socket_ipv4(mock_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_socket_factory()


@pytest.fixture
def mock_socket_ipv6(mock_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_socket_factory()


@pytest.fixture(autouse=True)
def mock_socket_cls(mock_socket_ipv4: MagicMock, mock_socket_ipv6: MagicMock, mocker: MockerFixture) -> MagicMock:
    def side_effect(family: int, type: int, proto: int) -> MagicMock:
        if family == AF_INET6:
            used_socket = mock_socket_ipv6
        elif family == AF_INET:
            used_socket = mock_socket_ipv4
        else:
            raise error_from_errno(errno.EAFNOSUPPORT)

        used_socket.family = family
        used_socket.type = type
        used_socket.proto = proto
        return used_socket

    return mocker.patch("socket.socket", side_effect=side_effect)


@pytest.mark.asyncio
async def test____ensure_resolved____try_numeric_first(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    expected_result = stream_addrinfo_list(8080, families=[AF_INET])
    mock_stdlib_socket_getaddrinfo.side_effect = None
    mock_stdlib_socket_getaddrinfo.return_value = expected_result

    # Act
    info = await dns_resolver.ensure_resolved(
        asyncio_backend,
        "127.0.0.1",
        8080,
        123456789,
        SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE,
    )

    # Assert
    assert info == expected_result
    mock_stdlib_socket_getaddrinfo.assert_called_once_with(
        "127.0.0.1",
        8080,
        family=123456789,
        type=SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE | AI_NUMERICHOST | AI_NUMERICSERV,
    )
    dns_resolver.mock_async_getaddrinfo.assert_not_awaited()


@pytest.mark.asyncio
async def test____ensure_resolved____try_numeric_first____success_but_return_empty_list(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    mock_stdlib_socket_getaddrinfo.side_effect = None
    mock_stdlib_socket_getaddrinfo.return_value = []

    # Act
    with pytest.raises(OSError, match=r"^getaddrinfo\('127.0.0.1'\) returned empty list$"):
        await dns_resolver.ensure_resolved(
            asyncio_backend,
            "127.0.0.1",
            8080,
            123456789,
            SOCK_STREAM,
            proto=IPPROTO_TCP,
            flags=AI_PASSIVE,
        )

    # Assert
    mock_stdlib_socket_getaddrinfo.assert_called_once_with(
        "127.0.0.1",
        8080,
        family=123456789,
        type=SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE | AI_NUMERICHOST | AI_NUMERICSERV,
    )
    dns_resolver.mock_async_getaddrinfo.assert_not_awaited()


@pytest.mark.asyncio
async def test____ensure_resolved____fallback_to_async_getaddrinfo(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    expected_result = stream_addrinfo_list(8080, families=[AF_INET])
    mock_stdlib_socket_getaddrinfo.side_effect = gaierror(EAI_NONAME, "Name or service not known")
    dns_resolver.mock_async_getaddrinfo.return_value = expected_result

    # Act
    info = await dns_resolver.ensure_resolved(
        asyncio_backend,
        "127.0.0.1",
        8080,
        123456789,
        SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE,
    )

    # Assert
    assert info == expected_result
    dns_resolver.mock_async_getaddrinfo.assert_awaited_once_with(
        "127.0.0.1",
        8080,
        family=123456789,
        type=SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE,
    )


@pytest.mark.asyncio
async def test____ensure_resolved____fallback_to_async_getaddrinfo____success_but_return_empty_list(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    mock_stdlib_socket_getaddrinfo.side_effect = gaierror(EAI_NONAME, "Name or service not known")
    dns_resolver.mock_async_getaddrinfo.return_value = []

    # Act
    with pytest.raises(OSError, match=r"^getaddrinfo\('127.0.0.1'\) returned empty list$"):
        await dns_resolver.ensure_resolved(
            asyncio_backend,
            "127.0.0.1",
            8080,
            123456789,
            SOCK_STREAM,
            proto=IPPROTO_TCP,
            flags=AI_PASSIVE,
        )

    # Assert
    dns_resolver.mock_async_getaddrinfo.assert_awaited_once_with(
        "127.0.0.1",
        8080,
        family=123456789,
        type=SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE,
    )


@pytest.mark.asyncio
async def test____ensure_resolved____propagate_unrelated_gaierror(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    mock_stdlib_socket_getaddrinfo.side_effect = gaierror(EAI_BADFLAGS, "Invalid flags")

    # Act
    with pytest.raises(gaierror):
        await dns_resolver.ensure_resolved(
            asyncio_backend,
            "127.0.0.1",
            8080,
            123456789,
            SOCK_STREAM,
            proto=IPPROTO_TCP,
            flags=AI_PASSIVE,
        )

    # Assert
    mock_stdlib_socket_getaddrinfo.assert_called_once_with(
        "127.0.0.1",
        8080,
        family=123456789,
        type=SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE | AI_NUMERICHOST | AI_NUMERICSERV,
    )
    dns_resolver.mock_async_getaddrinfo.assert_not_awaited()


@pytest.mark.asyncio
async def test____resolve_listener_addresses____bind_to_any_interfaces(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
) -> None:
    # Arrange
    local_port = 5000
    addrinfo_list = [
        (
            AF_INET,
            SOCK_STREAM,
            IPPROTO_TCP,
            "",
            ("0.0.0.0", local_port),
        ),
        (
            AF_INET6,
            SOCK_STREAM,
            IPPROTO_TCP,
            "",
            ("::", local_port),
        ),
    ]
    dns_resolver.mock_async_getaddrinfo.return_value = addrinfo_list

    # Act
    listeners_addrinfo = await dns_resolver.resolve_listener_addresses(
        asyncio_backend,
        hosts=[None],
        port=local_port,
        socktype=SOCK_STREAM,
    )

    # Assert
    dns_resolver.mock_async_getaddrinfo.assert_awaited_once_with(
        None,
        local_port,
        family=AF_UNSPEC,
        type=SOCK_STREAM,
        proto=0,
        flags=AI_PASSIVE | AI_ADDRCONFIG,
    )
    assert listeners_addrinfo == sorted(addrinfo_list)


@pytest.mark.asyncio
async def test____resolve_listener_addresses____bind_to_several_hosts(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    mocker: MockerFixture,
) -> None:
    # Arrange
    local_hosts = ["0.0.0.0", "::"]
    local_port = 5000
    addrinfo_list = [
        (
            AF_INET,
            SOCK_STREAM,
            IPPROTO_TCP,
            "",
            ("0.0.0.0", local_port),
        ),
        (
            AF_INET6,
            SOCK_STREAM,
            IPPROTO_TCP,
            "",
            ("::", local_port),
        ),
    ]
    dns_resolver.mock_async_getaddrinfo.side_effect = [[info] for info in addrinfo_list]

    # Act
    listeners_addrinfo = await dns_resolver.resolve_listener_addresses(
        asyncio_backend,
        hosts=local_hosts,
        port=local_port,
        socktype=SOCK_STREAM,
    )

    # Assert
    assert dns_resolver.mock_async_getaddrinfo.await_args_list == [
        mocker.call(
            host,
            local_port,
            family=AF_UNSPEC,
            type=SOCK_STREAM,
            proto=0,
            flags=AI_PASSIVE | AI_ADDRCONFIG,
        )
        for host in local_hosts
    ]
    assert listeners_addrinfo == sorted(addrinfo_list)


@pytest.mark.asyncio
async def test____resolve_listener_addresses____error_getaddrinfo_returns_empty_list(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
) -> None:
    # Arrange
    local_host = "localhost"
    local_port = 5000

    dns_resolver.mock_async_getaddrinfo.return_value = []

    # Act
    with pytest.raises(ExceptionGroup) as exc_info:
        await dns_resolver.resolve_listener_addresses(
            asyncio_backend,
            hosts=[local_host],
            port=local_port,
            socktype=SOCK_STREAM,
        )

    # Assert
    assert exc_info.group_contains(OSError, match=r"^getaddrinfo\('localhost'\) returned empty list$")

    dns_resolver.mock_async_getaddrinfo.assert_awaited_once_with(
        local_host,
        local_port,
        family=AF_UNSPEC,
        type=SOCK_STREAM,
        proto=0,
        flags=AI_PASSIVE | AI_ADDRCONFIG,
    )


class _CreateConnectionCallable(TypingProtocol):
    async def __call__(
        self,
        backend: AsyncBackend,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = None,
    ) -> SocketType: ...


class _AddrInfoListFactory(TypingProtocol):
    def __call__(
        self,
        port: int,
        families: Sequence[int] = ...,
    ) -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]: ...


@pytest.fixture(params=[SOCK_STREAM, SOCK_DGRAM], ids=lambda sock_type: f"sock_type=={sock_type!r}")
def connection_socktype(request: pytest.FixtureRequest) -> int:
    return request.param


@pytest.fixture
def addrinfo_list_factory(connection_socktype: int) -> _AddrInfoListFactory:
    if connection_socktype == SOCK_STREAM:
        return stream_addrinfo_list
    if connection_socktype == SOCK_DGRAM:
        return datagram_addrinfo_list
    pytest.fail("Invalid fixture argument")


def create_connection_of_socktype(dns_resolver: MockedDNSResolver, connection_socktype: int) -> _CreateConnectionCallable:
    if connection_socktype == SOCK_STREAM:
        return dns_resolver.create_stream_connection
    if connection_socktype == SOCK_DGRAM:
        return dns_resolver.create_datagram_connection
    pytest.fail("Invalid fixture argument")


@pytest.mark.asyncio
@pytest.mark.parametrize("with_local_address", [False, True], ids=lambda boolean: f"with_local_address=={boolean}")
async def test____create_connection____default(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    connection_socktype: int,
    with_local_address: bool,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    expected_proto = IPPROTO_TCP if connection_socktype == SOCK_STREAM else IPPROTO_UDP
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] | None = ("localhost", 11111) if with_local_address else None

    if local_address is None:
        dns_resolver.mock_async_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port)]
    else:
        dns_resolver.mock_async_getaddrinfo.side_effect = [
            addrinfo_list_factory(remote_port),
            addrinfo_list_factory(local_address[1]),
        ]

    # Act
    socket = await create_connection_of_socktype(dns_resolver, connection_socktype)(
        asyncio_backend,
        remote_host,
        remote_port,
        local_address=local_address,
    )

    # Assert
    if local_address is None:
        assert dns_resolver.mock_async_getaddrinfo.await_args_list == [
            mocker.call(remote_host, remote_port, family=AF_UNSPEC, type=connection_socktype, proto=0, flags=0),
        ]
    else:
        assert dns_resolver.mock_async_getaddrinfo.await_args_list == [
            mocker.call(remote_host, remote_port, family=AF_UNSPEC, type=connection_socktype, proto=0, flags=0),
            mocker.call(*local_address, family=AF_UNSPEC, type=connection_socktype, proto=0, flags=0),
        ]

    mock_socket_cls.assert_called_once_with(AF_INET6, connection_socktype, expected_proto)
    assert socket is mock_socket_ipv6

    mock_socket_ipv6.setblocking.assert_called_once_with(False)
    if local_address is None:
        mock_socket_ipv6.bind.assert_not_called()
    else:
        mock_socket_ipv6.bind.assert_called_once_with(("::1", 11111, 0, 0))
    dns_resolver.mock_sock_connect.assert_awaited_once_with(mock_socket_ipv6, ("::1", 12345, 0, 0))
    mock_socket_ipv6.close.assert_not_called()

    mock_socket_ipv4.setblocking.assert_not_called()
    mock_socket_ipv4.bind.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____first_failed(
    fail_on: Literal["socket", "bind", "connect"],
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    connection_socktype: int,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] | None = ("localhost", 11111) if fail_on == "bind" else None

    if local_address is None:
        dns_resolver.mock_async_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port)]
    else:
        dns_resolver.mock_async_getaddrinfo.side_effect = [
            addrinfo_list_factory(remote_port),
            addrinfo_list_factory(local_address[1]),
        ]

    match fail_on:
        case "socket":
            mock_socket_cls.side_effect = [error_from_errno(errno.EAFNOSUPPORT), mock_socket_ipv4]
        case "bind":
            mock_socket_ipv6.bind.side_effect = error_from_errno(errno.EADDRINUSE)
        case "connect":
            dns_resolver.mock_sock_connect.side_effect = [error_from_errno(errno.ECONNREFUSED), None]
        case _:
            assert_never(fail_on)

    # Act
    socket = await create_connection_of_socktype(dns_resolver, connection_socktype)(
        asyncio_backend,
        remote_host,
        remote_port,
        local_address=local_address,
    )

    # Assert
    if connection_socktype == SOCK_STREAM:
        assert mock_socket_cls.call_args_list == [
            mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
            mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
        ]
    else:
        assert mock_socket_cls.call_args_list == [
            mocker.call(AF_INET6, SOCK_DGRAM, IPPROTO_UDP),
            mocker.call(AF_INET, SOCK_DGRAM, IPPROTO_UDP),
        ]
    assert socket is mock_socket_ipv4

    if fail_on != "socket":
        if fail_on != "bind":
            mock_socket_ipv6.setblocking.assert_called_once_with(False)
        if local_address is None:
            mock_socket_ipv6.bind.assert_not_called()
        else:
            mock_socket_ipv6.bind.assert_called_once_with(("::1", 11111, 0, 0))
        match fail_on:
            case "bind":
                assert mocker.call(mock_socket_ipv6, ("::1", 12345, 0, 0)) not in dns_resolver.mock_sock_connect.await_args_list
            case "connect":
                dns_resolver.mock_sock_connect.assert_any_await(mock_socket_ipv6, ("::1", 12345, 0, 0))
            case _:
                assert_never(fail_on)
        mock_socket_ipv6.close.assert_called_once_with()

    mock_socket_ipv4.setblocking.assert_called_once_with(False)
    if local_address is None:
        mock_socket_ipv4.bind.assert_not_called()
    else:
        mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 11111))
    dns_resolver.mock_sock_connect.assert_awaited_with(mock_socket_ipv4, ("127.0.0.1", 12345))
    mock_socket_ipv4.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____all_failed(
    fail_on: Literal["socket", "bind", "connect"],
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    connection_socktype: int,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] | None = ("localhost", 11111) if fail_on == "bind" else None

    if local_address is None:
        dns_resolver.mock_async_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port)]
    else:
        dns_resolver.mock_async_getaddrinfo.side_effect = [
            addrinfo_list_factory(remote_port),
            addrinfo_list_factory(local_address[1]),
        ]

    match fail_on:
        case "socket":
            mock_socket_cls.side_effect = error_from_errno(errno.EAFNOSUPPORT)
        case "bind":
            mock_socket_ipv4.bind.side_effect = error_from_errno(errno.EADDRINUSE)
            mock_socket_ipv6.bind.side_effect = error_from_errno(errno.EADDRINUSE)
        case "connect":
            dns_resolver.mock_sock_connect.side_effect = error_from_errno(errno.ECONNREFUSED)
        case _:
            assert_never(fail_on)

    # Act
    with pytest.raises(ExceptionGroup) as exc_info:
        await create_connection_of_socktype(dns_resolver, connection_socktype)(
            asyncio_backend,
            remote_host,
            remote_port,
            local_address=local_address,
        )

    # Assert
    os_errors, exc = exc_info.value.split(OSError)
    assert exc is None
    assert os_errors is not None
    assert len(os_errors.exceptions) == 2
    assert all(isinstance(exc, OSError) for exc in os_errors.exceptions)
    del os_errors

    if connection_socktype == SOCK_STREAM:
        assert mock_socket_cls.call_args_list == [
            mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
            mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
        ]
    else:
        assert mock_socket_cls.call_args_list == [
            mocker.call(AF_INET6, SOCK_DGRAM, IPPROTO_UDP),
            mocker.call(AF_INET, SOCK_DGRAM, IPPROTO_UDP),
        ]

    if fail_on != "socket":
        if fail_on != "bind":
            mock_socket_ipv4.setblocking.assert_called_once_with(False)
            mock_socket_ipv6.setblocking.assert_called_once_with(False)
        if local_address is None:
            mock_socket_ipv4.bind.assert_not_called()
            mock_socket_ipv6.bind.assert_not_called()
        else:
            mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 11111))
            mock_socket_ipv6.bind.assert_called_once_with(("::1", 11111, 0, 0))
        match fail_on:
            case "bind" | "socket":
                assert mocker.call(mock_socket_ipv4, ("127.0.0.1", 12345)) not in dns_resolver.mock_sock_connect.await_args_list
                assert mocker.call(mock_socket_ipv6, ("::1", 12345, 0, 0)) not in dns_resolver.mock_sock_connect.await_args_list
            case "connect":
                dns_resolver.mock_sock_connect.assert_any_await(mock_socket_ipv4, ("127.0.0.1", 12345))
                dns_resolver.mock_sock_connect.assert_any_await(mock_socket_ipv6, ("::1", 12345, 0, 0))
            case _:
                assert_never(fail_on)
        mock_socket_ipv4.close.assert_called_once_with()
        mock_socket_ipv6.close.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____unrelated_exception(
    fail_on: Literal["socket", "connect"],
    connection_socktype: int,
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv6: MagicMock,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345

    dns_resolver.mock_async_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port)]
    expected_failure_exception = BaseException()

    match fail_on:
        case "socket":
            mock_socket_cls.side_effect = expected_failure_exception
        case "connect":
            dns_resolver.mock_sock_connect.side_effect = expected_failure_exception
        case _:
            assert_never(fail_on)

    # Act
    with pytest.raises(BaseException) as exc_info:
        await create_connection_of_socktype(dns_resolver, connection_socktype)(asyncio_backend, remote_host, remote_port)

    # Assert
    if connection_socktype == SOCK_STREAM:
        assert isinstance(exc_info.value, BaseExceptionGroup)
        assert len(exc_info.value.exceptions) == 1
        assert exc_info.value.exceptions[0] is expected_failure_exception
    else:
        assert exc_info.value is expected_failure_exception
    if fail_on != "socket":
        mock_socket_ipv6.close.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["remote_address", "local_address"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____getaddrinfo_returned_empty_list(
    fail_on: Literal["remote_address", "local_address"],
    connection_socktype: int,
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] = ("localhost", 11111)

    match fail_on:
        case "remote_address":
            dns_resolver.mock_async_getaddrinfo.side_effect = [[]]
        case "local_address":
            dns_resolver.mock_async_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port), []]
        case _:
            assert_never(fail_on)

    # Act
    with pytest.raises(OSError, match=r"getaddrinfo\('localhost'\) returned empty list"):
        await create_connection_of_socktype(dns_resolver, connection_socktype)(
            asyncio_backend,
            remote_host,
            remote_port,
            local_address=local_address,
        )

    # Assert
    mock_socket_cls.assert_not_called()
    mock_socket_ipv4.bind.assert_not_called()
    mock_socket_ipv6.bind.assert_not_called()
    dns_resolver.mock_sock_connect.assert_not_called()


@pytest.mark.asyncio
async def test____create_connection____getaddrinfo_return_mismatch(
    connection_socktype: int,
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] = ("localhost", 11111)

    dns_resolver.mock_async_getaddrinfo.side_effect = [
        addrinfo_list_factory(remote_port, families=[AF_INET6]),
        addrinfo_list_factory(local_address[1], families=[AF_INET]),
    ]

    # Act
    with pytest.raises(ExceptionGroup) as exc_info:
        await create_connection_of_socktype(dns_resolver, connection_socktype)(
            asyncio_backend,
            remote_host,
            remote_port,
            local_address=local_address,
        )

    # Assert
    os_errors, exc = exc_info.value.split(OSError)
    assert exc is None
    assert os_errors is not None
    assert len(os_errors.exceptions) == 1
    assert str(os_errors.exceptions[0]) == f"no matching local address with family={AF_INET6!r} found"
    del os_errors

    mock_socket_ipv4.bind.assert_not_called()
    mock_socket_ipv6.bind.assert_not_called()
    dns_resolver.mock_sock_connect.assert_not_called()


@PlatformMarkers.skipif_platform_bsd_because("test failures are all too frequent on CI", skip_only_on_ci=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("connection_socktype", [SOCK_STREAM], indirect=True, ids=repr)
@pytest.mark.flaky(retries=3)
async def test____create_stream_connection____happy_eyeballs_delay____connect_cancellation(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    event_loop = asyncio.get_running_loop()
    timestamps: list[float] = []
    remote_host, remote_port = "localhost", 12345
    dns_resolver.mock_async_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port, families=[AF_INET6, AF_INET])]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        timestamps.append(event_loop.time())
        if sock.family == AF_INET6:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.01)

    dns_resolver.mock_sock_connect.side_effect = connect_side_effect

    # Act
    socket = await dns_resolver.create_stream_connection(asyncio_backend, remote_host, remote_port, happy_eyeballs_delay=0.5)

    # Assert
    assert socket is mock_socket_ipv4
    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
    ]

    mock_socket_ipv6.close.assert_called_once_with()
    mock_socket_ipv4.close.assert_not_called()

    ipv6_start_time, ipv4_start_time = timestamps
    assert ipv4_start_time - ipv6_start_time == pytest.approx(0.5, rel=1e-1)


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_socktype", [SOCK_STREAM], indirect=True, ids=repr)
async def test____create_stream_connection____happy_eyeballs_delay____connect_too_late(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    dns_resolver.mock_async_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port, families=[AF_INET6, AF_INET])]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            TaskUtils.current_asyncio_task().uncancel()
            await asyncio.sleep(0)

    dns_resolver.mock_sock_connect.side_effect = connect_side_effect

    # Act
    socket = await dns_resolver.create_stream_connection(asyncio_backend, remote_host, remote_port, happy_eyeballs_delay=0.25)

    # Assert
    assert socket is mock_socket_ipv6
    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
    ]

    mock_socket_ipv4.close.assert_called_once_with()
    mock_socket_ipv6.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_socktype", [SOCK_STREAM], indirect=True, ids=repr)
async def test____create_stream_connection____happy_eyeballs_delay____winner_closed_because_of_exception_in_another_task(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    expected_failure_exception = Exception("error")
    remote_host, remote_port = "localhost", 12345
    dns_resolver.mock_async_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port, families=[AF_INET6, AF_INET])]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise expected_failure_exception from None

    dns_resolver.mock_sock_connect.side_effect = connect_side_effect

    # Act
    with pytest.raises(ExceptionGroup) as exc_info:
        await dns_resolver.create_stream_connection(asyncio_backend, remote_host, remote_port, happy_eyeballs_delay=0.25)
    while TaskUtils.current_asyncio_task().uncancel():
        continue

    # Assert
    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
    ]
    assert list(exc_info.value.exceptions) == [expected_failure_exception]

    mock_socket_ipv4.close.assert_called_once_with()
    mock_socket_ipv6.close.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_socktype", [SOCK_STREAM], indirect=True, ids=repr)
async def test____create_stream_connection____happy_eyeballs_delay____addrinfo_reordering____prioritize_ipv6_over_ipv4(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv6: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    dns_resolver.mock_async_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port, families=[AF_INET, AF_INET6])]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        await asyncio.sleep(0.5)

    dns_resolver.mock_sock_connect.side_effect = connect_side_effect

    # Act
    socket = await dns_resolver.create_stream_connection(asyncio_backend, remote_host, remote_port, happy_eyeballs_delay=0.25)

    # Assert
    assert socket is mock_socket_ipv6
    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_socktype", [SOCK_STREAM], indirect=True, ids=repr)
async def test____create_stream_connection____happy_eyeballs_delay____addrinfo_reordering____interleave_families(
    asyncio_backend: AsyncBackend,
    dns_resolver: MockedDNSResolver,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv6: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    dns_resolver.mock_async_getaddrinfo.side_effect = [
        addrinfo_list_factory(remote_port, families=[AF_INET6, AF_INET6, AF_INET6, AF_INET, AF_INET, AF_INET]),
    ]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        await asyncio.sleep(1)

    dns_resolver.mock_sock_connect.side_effect = connect_side_effect

    # Act
    socket = await dns_resolver.create_stream_connection(asyncio_backend, remote_host, remote_port, happy_eyeballs_delay=0.1)

    # Assert
    assert socket is mock_socket_ipv6
    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("socket_family_name", unsupported_families(INET_FAMILIES))
async def test____create_datagram_connection____invalid_socket_family(
    asyncio_backend: AsyncBackend,
    socket_family_name: str,
    dns_resolver: MockedDNSResolver,
    mock_socket_cls: MagicMock,
) -> None:
    # Arrange
    socket_family = socket_family_or_skip(socket_family_name)
    remote_host, remote_port = "localhost", 12345
    dns_resolver.mock_async_getaddrinfo.side_effect = []
    dns_resolver.mock_sock_connect.side_effect = []

    # Act
    with pytest.raises(ValueError, match=r"^Only these families are supported: AF_INET, AF_INET6$"):
        _ = await dns_resolver.create_datagram_connection(asyncio_backend, remote_host, remote_port, family=socket_family)

    # Assert
    dns_resolver.mock_async_getaddrinfo.assert_not_called()
    dns_resolver.mock_sock_connect.assert_not_called()
    mock_socket_cls.assert_not_called()
