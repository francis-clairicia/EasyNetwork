from __future__ import annotations

import asyncio
import asyncio.trsock
import errno
from collections.abc import Callable, Sequence
from socket import (
    AF_INET,
    AF_INET6,
    AF_UNSPEC,
    AI_NUMERICHOST,
    AI_NUMERICSERV,
    AI_PASSIVE,
    EAI_BADFLAGS,
    EAI_NONAME,
    IPPROTO_IPV6,
    IPPROTO_TCP,
    IPPROTO_UDP,
    IPV6_V6ONLY,
    SO_REUSEADDR,
    SOCK_DGRAM,
    SOCK_STREAM,
    SOL_SOCKET,
    gaierror,
)
from typing import TYPE_CHECKING, Any, Literal, assert_never, cast

from easynetwork.lowlevel._utils import error_from_errno
from easynetwork.lowlevel.asyncio._asyncio_utils import (
    create_connection,
    ensure_resolved,
    open_listener_sockets_from_getaddrinfo_result,
)

import pytest

from ..._utils import datagram_addrinfo_list, stream_addrinfo_list

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_getaddrinfo(event_loop: asyncio.AbstractEventLoop, mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(event_loop, "getaddrinfo", new_callable=mocker.AsyncMock)


@pytest.fixture
def mock_stdlib_socket_getaddrinfo(mocker: MockerFixture) -> AsyncMock:
    return mocker.patch("socket.getaddrinfo")


@pytest.fixture
def mock_sock_connect(event_loop: asyncio.AbstractEventLoop, mocker: MockerFixture) -> AsyncMock:
    return mocker.patch.object(event_loop, "sock_connect", new_callable=mocker.AsyncMock, return_value=None)


@pytest.fixture
def mock_socket_ipv4(mock_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_socket_factory()


@pytest.fixture
def mock_socket_ipv6(mock_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_socket_factory()


@pytest.fixture(autouse=True)
def mock_socket_cls(mock_socket_ipv4: MagicMock, mock_socket_ipv6: MagicMock, mocker: MockerFixture) -> MagicMock:
    return mocker.patch("socket.socket", side_effect=[mock_socket_ipv4, mock_socket_ipv6])


@pytest.mark.asyncio
async def test____ensure_resolved____try_numeric_first(
    event_loop: asyncio.AbstractEventLoop,
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    expected_result = stream_addrinfo_list(8080, families=[AF_INET])
    mock_stdlib_socket_getaddrinfo.return_value = expected_result

    # Act
    info = await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, event_loop, proto=IPPROTO_TCP, flags=AI_PASSIVE)

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
    mock_getaddrinfo.assert_not_awaited()


@pytest.mark.asyncio
async def test____ensure_resolved____try_numeric_first____success_but_return_empty_list(
    event_loop: asyncio.AbstractEventLoop,
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    mock_stdlib_socket_getaddrinfo.return_value = []

    # Act
    with pytest.raises(OSError, match=r"^getaddrinfo\('127.0.0.1'\) returned empty list$"):
        await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, event_loop, proto=IPPROTO_TCP, flags=AI_PASSIVE)

    # Assert
    mock_stdlib_socket_getaddrinfo.assert_called_once_with(
        "127.0.0.1",
        8080,
        family=123456789,
        type=SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE | AI_NUMERICHOST | AI_NUMERICSERV,
    )
    mock_getaddrinfo.assert_not_awaited()


@pytest.mark.asyncio
async def test____ensure_resolved____fallback_to_async_getaddrinfo(
    event_loop: asyncio.AbstractEventLoop,
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    expected_result = stream_addrinfo_list(8080, families=[AF_INET])
    mock_stdlib_socket_getaddrinfo.side_effect = gaierror(EAI_NONAME, "Name or service not known")
    mock_getaddrinfo.return_value = expected_result

    # Act
    info = await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, event_loop, proto=IPPROTO_TCP, flags=AI_PASSIVE)

    # Assert
    assert info == expected_result
    mock_getaddrinfo.assert_awaited_once_with(
        "127.0.0.1",
        8080,
        family=123456789,
        type=SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE,
    )


@pytest.mark.asyncio
async def test____ensure_resolved____fallback_to_async_getaddrinfo____success_but_return_empty_list(
    event_loop: asyncio.AbstractEventLoop,
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    mock_stdlib_socket_getaddrinfo.side_effect = gaierror(EAI_NONAME, "Name or service not known")
    mock_getaddrinfo.return_value = []

    # Act
    with pytest.raises(OSError, match=r"^getaddrinfo\('127.0.0.1'\) returned empty list$"):
        await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, event_loop, proto=IPPROTO_TCP, flags=AI_PASSIVE)

    # Assert
    mock_getaddrinfo.assert_awaited_once_with(
        "127.0.0.1",
        8080,
        family=123456789,
        type=SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE,
    )


@pytest.mark.asyncio
async def test____ensure_resolved____propagate_unrelated_gaierror(
    event_loop: asyncio.AbstractEventLoop,
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    mock_stdlib_socket_getaddrinfo.side_effect = gaierror(EAI_BADFLAGS, "Invalid flags")

    # Act
    with pytest.raises(gaierror):
        await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, event_loop, proto=IPPROTO_TCP, flags=AI_PASSIVE)

    # Assert
    mock_stdlib_socket_getaddrinfo.assert_called_once_with(
        "127.0.0.1",
        8080,
        family=123456789,
        type=SOCK_STREAM,
        proto=IPPROTO_TCP,
        flags=AI_PASSIVE | AI_NUMERICHOST | AI_NUMERICSERV,
    )
    mock_getaddrinfo.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_local_address", [False, True], ids=lambda boolean: f"with_local_address=={boolean}")
@pytest.mark.parametrize("sock_type", [None, SOCK_STREAM, SOCK_DGRAM], ids=lambda sock_type: f"sock_type=={sock_type!r}")
async def test____create_connection____default(
    event_loop: asyncio.AbstractEventLoop,
    sock_type: int | None,
    with_local_address: bool,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    expected_sock_type = SOCK_STREAM if sock_type is None else sock_type
    expected_proto = IPPROTO_TCP if expected_sock_type == SOCK_STREAM else IPPROTO_UDP
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] | None = ("localhost", 11111) if with_local_address else None

    if local_address is None:
        if expected_sock_type == SOCK_STREAM:
            mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port)]
        else:
            mock_getaddrinfo.side_effect = [datagram_addrinfo_list(remote_port)]
    else:
        if expected_sock_type == SOCK_STREAM:
            mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port), stream_addrinfo_list(local_address[1])]
        else:
            mock_getaddrinfo.side_effect = [datagram_addrinfo_list(remote_port), datagram_addrinfo_list(local_address[1])]

    # Act
    if sock_type is None:
        socket = await create_connection(remote_host, remote_port, event_loop, local_address=local_address)
    else:
        socket = await create_connection(remote_host, remote_port, event_loop, local_address=local_address, socktype=sock_type)

    # Assert
    if local_address is None:
        assert mock_getaddrinfo.await_args_list == [
            mocker.call(remote_host, remote_port, family=AF_UNSPEC, type=expected_sock_type, proto=0, flags=0),
        ]
    else:
        assert mock_getaddrinfo.await_args_list == [
            mocker.call(remote_host, remote_port, family=AF_UNSPEC, type=expected_sock_type, proto=0, flags=0),
            mocker.call(*local_address, family=AF_UNSPEC, type=expected_sock_type, proto=0, flags=0),
        ]

    mock_socket_cls.assert_called_once_with(AF_INET, expected_sock_type, expected_proto)
    assert socket is mock_socket_ipv4

    mock_socket_ipv4.setblocking.assert_called_once_with(False)
    if local_address is None:
        mock_socket_ipv4.bind.assert_not_called()
    else:
        mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 11111))
    mock_sock_connect.assert_awaited_once_with(mock_socket_ipv4, ("127.0.0.1", 12345))
    mock_socket_ipv4.close.assert_not_called()

    mock_socket_ipv6.setblocking.assert_not_called()
    mock_socket_ipv6.bind.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____first_failed(
    event_loop: asyncio.AbstractEventLoop,
    fail_on: Literal["socket", "bind", "connect"],
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] | None = ("localhost", 11111) if fail_on == "bind" else None

    if local_address is None:
        mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port)]
    else:
        mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port), stream_addrinfo_list(local_address[1])]

    match fail_on:
        case "socket":
            mock_socket_cls.side_effect = [error_from_errno(errno.EAFNOSUPPORT), mock_socket_ipv6]
        case "bind":
            mock_socket_ipv4.bind.side_effect = error_from_errno(errno.EADDRINUSE)
        case "connect":
            mock_sock_connect.side_effect = [error_from_errno(errno.ECONNREFUSED), None]
        case _:
            assert_never(fail_on)

    # Act
    socket = await create_connection(remote_host, remote_port, event_loop, local_address=local_address)

    # Assert
    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
    ]
    assert socket is mock_socket_ipv6

    if fail_on != "socket":
        mock_socket_ipv4.setblocking.assert_called_once_with(False)
        if local_address is None:
            mock_socket_ipv4.bind.assert_not_called()
        else:
            mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 11111))
        match fail_on:
            case "bind":
                assert mocker.call(mock_socket_ipv4, ("127.0.0.1", 12345)) not in mock_sock_connect.await_args_list
            case "connect":
                mock_sock_connect.assert_any_await(mock_socket_ipv4, ("127.0.0.1", 12345))
            case _:
                assert_never(fail_on)
        mock_socket_ipv4.close.assert_called_once_with()

    mock_socket_ipv6.setblocking.assert_called_once_with(False)
    if local_address is None:
        mock_socket_ipv6.bind.assert_not_called()
    else:
        mock_socket_ipv6.bind.assert_called_once_with(("::1", 11111, 0, 0))
    mock_sock_connect.assert_awaited_with(mock_socket_ipv6, ("::1", 12345, 0, 0))
    mock_socket_ipv6.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____all_failed(
    event_loop: asyncio.AbstractEventLoop,
    fail_on: Literal["socket", "bind", "connect"],
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] | None = ("localhost", 11111) if fail_on == "bind" else None

    if local_address is None:
        mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port)]
    else:
        mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port), stream_addrinfo_list(local_address[1])]

    match fail_on:
        case "socket":
            mock_socket_cls.side_effect = error_from_errno(errno.EAFNOSUPPORT)
        case "bind":
            mock_socket_ipv4.bind.side_effect = error_from_errno(errno.EADDRINUSE)
            mock_socket_ipv6.bind.side_effect = error_from_errno(errno.EADDRINUSE)
        case "connect":
            mock_sock_connect.side_effect = error_from_errno(errno.ECONNREFUSED)
        case _:
            assert_never(fail_on)

    # Act
    with pytest.raises(ExceptionGroup) as exc_info:
        await create_connection(remote_host, remote_port, event_loop, local_address=local_address)

    # Assert
    os_errors, exc = exc_info.value.split(OSError)
    assert exc is None
    assert os_errors is not None
    assert len(os_errors.exceptions) == 2
    assert all(isinstance(exc, OSError) for exc in os_errors.exceptions)
    del os_errors

    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
    ]

    if fail_on != "socket":
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
                assert mocker.call(mock_socket_ipv4, ("127.0.0.1", 12345)) not in mock_sock_connect.await_args_list
                assert mocker.call(mock_socket_ipv6, ("::1", 12345, 0, 0)) not in mock_sock_connect.await_args_list
            case "connect":
                mock_sock_connect.assert_any_await(mock_socket_ipv4, ("127.0.0.1", 12345))
                mock_sock_connect.assert_any_await(mock_socket_ipv6, ("::1", 12345, 0, 0))
            case _:
                assert_never(fail_on)
        mock_socket_ipv4.close.assert_called_once_with()
        mock_socket_ipv6.close.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____unrelated_exception(
    event_loop: asyncio.AbstractEventLoop,
    fail_on: Literal["socket", "connect"],
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345

    mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port)]
    expected_failure_exception = BaseException()

    match fail_on:
        case "socket":
            mock_socket_cls.side_effect = expected_failure_exception
        case "connect":
            mock_sock_connect.side_effect = expected_failure_exception
        case _:
            assert_never(fail_on)

    # Act
    with pytest.raises(BaseException) as exc_info:
        await create_connection(remote_host, remote_port, event_loop)

    # Assert
    assert exc_info.value is expected_failure_exception
    if fail_on != "socket":
        mock_socket_ipv4.close.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["remote_address", "local_address"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____getaddrinfo_returned_empty_list(
    event_loop: asyncio.AbstractEventLoop,
    fail_on: Literal["remote_address", "local_address"],
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] = ("localhost", 11111)

    match fail_on:
        case "remote_address":
            mock_getaddrinfo.side_effect = [[]]
        case "local_address":
            mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port), []]
        case _:
            assert_never(fail_on)

    # Act
    with pytest.raises(OSError, match=r"^getaddrinfo\('localhost'\) returned empty list$"):
        await create_connection(remote_host, remote_port, event_loop, local_address=local_address)

    # Assert
    mock_socket_cls.assert_not_called()
    mock_socket_ipv4.bind.assert_not_called()
    mock_socket_ipv6.bind.assert_not_called()
    mock_sock_connect.assert_not_called()


@pytest.mark.asyncio
async def test____create_connection____getaddrinfo_return_mismatch(
    event_loop: asyncio.AbstractEventLoop,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] = ("localhost", 11111)

    mock_getaddrinfo.side_effect = [
        stream_addrinfo_list(remote_port, families=[AF_INET6]),
        stream_addrinfo_list(local_address[1], families=[AF_INET]),
    ]

    # Act
    with pytest.raises(ExceptionGroup) as exc_info:
        await create_connection(remote_host, remote_port, event_loop, local_address=local_address)

    # Assert
    os_errors, exc = exc_info.value.split(OSError)
    assert exc is None
    assert os_errors is not None
    assert len(os_errors.exceptions) == 1
    assert str(os_errors.exceptions[0]) == f"no matching local address with family={AF_INET6!r} found"
    del os_errors

    mock_socket_ipv4.bind.assert_not_called()
    mock_socket_ipv6.bind.assert_not_called()
    mock_sock_connect.assert_not_called()


@pytest.fixture
def addrinfo_list() -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    return (
        (AF_INET, SOCK_STREAM, IPPROTO_TCP, "", ("0.0.0.0", 65432)),
        (AF_INET6, SOCK_STREAM, IPPROTO_TCP, "", ("::", 65432, 0, 0)),
    )


@pytest.mark.parametrize("reuse_address", [False, True], ids=lambda boolean: f"reuse_address=={boolean}")
@pytest.mark.parametrize("SO_REUSEADDR_available", [False, True], ids=lambda boolean: f"SO_REUSEADDR_available=={boolean}")
@pytest.mark.parametrize("SO_REUSEADDR_raise_error", [False, True], ids=lambda boolean: f"SO_REUSEADDR_raise_error=={boolean}")
@pytest.mark.parametrize("reuse_port", [False, True], ids=lambda boolean: f"reuse_port=={boolean}")
@pytest.mark.parametrize("backlog", [123456, None], ids=lambda value: f"backlog=={value}")
def test____open_listener_sockets_from_getaddrinfo_result____create_listener_sockets(
    reuse_address: bool,
    backlog: int | None,
    SO_REUSEADDR_available: bool,
    SO_REUSEADDR_raise_error: bool,
    reuse_port: bool,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mocker: MockerFixture,
    addrinfo_list: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
    monkeypatch: pytest.MonkeyPatch,
    SO_REUSEPORT: int,
) -> None:
    # Arrange
    if not SO_REUSEADDR_available:
        monkeypatch.delattr("socket.SO_REUSEADDR", raising=True)
    if SO_REUSEADDR_raise_error:

        def setsockopt(level: int, opt: int, value: int, /) -> None:
            if level == SOL_SOCKET and opt == SO_REUSEADDR:
                raise OSError

        mock_socket_ipv4.setsockopt.side_effect = setsockopt
        mock_socket_ipv6.setsockopt.side_effect = setsockopt

    # Act
    sockets = cast(
        "list[MagicMock]",
        open_listener_sockets_from_getaddrinfo_result(
            addrinfo_list,
            backlog=backlog,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
        ),
    )

    # Assert
    assert len(sockets) == len(addrinfo_list)
    assert mock_socket_cls.call_args_list == [mocker.call(f, t, p) for f, t, p, _, _ in addrinfo_list]
    for socket, (sock_family, _, _, _, sock_addr) in zip(sockets, addrinfo_list, strict=True):
        if reuse_address and SO_REUSEADDR_available:
            socket.setsockopt.assert_any_call(SOL_SOCKET, SO_REUSEADDR, True)
        if reuse_port:
            socket.setsockopt.assert_any_call(SOL_SOCKET, SO_REUSEPORT, True)
        if sock_family == AF_INET6:
            socket.setsockopt.assert_any_call(IPPROTO_IPV6, IPV6_V6ONLY, True)
        socket.bind.assert_called_once_with(sock_addr)
        if backlog is None:
            socket.listen.assert_not_called()
        else:
            socket.listen.assert_called_once_with(backlog)
        socket.close.assert_not_called()


def test____open_listener_sockets_from_getaddrinfo_result____ignore_bad_combinations(
    mock_socket_cls: MagicMock,
    mock_tcp_socket_factory: Callable[[], MagicMock],
    addrinfo_list: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
) -> None:
    # Arrange
    assert len(addrinfo_list) == 2  # In prevention
    mock_socket_cls.side_effect = [mock_tcp_socket_factory(), OSError]

    # Act
    sockets = open_listener_sockets_from_getaddrinfo_result(addrinfo_list, backlog=10, reuse_address=True, reuse_port=False)

    # Assert
    assert len(sockets) == 1


def test____open_listener_sockets_from_getaddrinfo_result____bind_failed(
    mock_socket_cls: MagicMock,
    mock_tcp_socket_factory: Callable[[], MagicMock],
    addrinfo_list: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
) -> None:
    # Arrange
    assert len(addrinfo_list) == 2  # In prevention
    s1, s2 = mock_tcp_socket_factory(), mock_tcp_socket_factory()
    mock_socket_cls.side_effect = [s1, s2]
    s2.bind.side_effect = OSError(1234, "error message")

    # Act
    with pytest.raises(ExceptionGroup, match=r"^Error when trying to create listeners \(1 sub-exception\)$") as exc_info:
        open_listener_sockets_from_getaddrinfo_result(addrinfo_list, backlog=10, reuse_address=True, reuse_port=False)

    # Assert
    os_errors, exc = exc_info.value.split(OSError)
    assert exc is None
    assert os_errors is not None
    assert len(os_errors.exceptions) == 1
    assert isinstance(os_errors.exceptions[0], OSError)
    assert os_errors.exceptions[0].errno == 1234

    s1.close.assert_called_once_with()
    s2.close.assert_called_once_with()
