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
from easynetwork_asyncio._utils import (
    create_connection,
    create_datagram_socket,
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
async def test____create_connection____default(
    event_loop: asyncio.AbstractEventLoop,
    with_local_address: bool,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] | None = ("localhost", 11111) if with_local_address else None

    if local_address is None:
        mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port)]
    else:
        mock_getaddrinfo.side_effect = [stream_addrinfo_list(remote_port), stream_addrinfo_list(local_address[1])]

    # Act
    socket = await create_connection(remote_host, remote_port, event_loop, local_address=local_address)

    # Assert
    if local_address is None:
        assert mock_getaddrinfo.await_args_list == [
            mocker.call(remote_host, remote_port, family=AF_UNSPEC, type=SOCK_STREAM, proto=0, flags=0),
        ]
    else:
        assert mock_getaddrinfo.await_args_list == [
            mocker.call(remote_host, remote_port, family=AF_UNSPEC, type=SOCK_STREAM, proto=0, flags=0),
            mocker.call(*local_address, family=AF_UNSPEC, type=SOCK_STREAM, proto=0, flags=0),
        ]

    mock_socket_cls.assert_called_once_with(AF_INET, SOCK_STREAM, IPPROTO_TCP)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("with_local_address", [False, True], ids=lambda boolean: f"with_local_address=={boolean}")
@pytest.mark.parametrize("with_remote_address", [False, True], ids=lambda boolean: f"with_remote_address=={boolean}")
@pytest.mark.parametrize("set_reuse_port", [False, True], ids=lambda boolean: f"set_reuse_port=={boolean}")
async def test____create_datagram_socket____default(
    event_loop: asyncio.AbstractEventLoop,
    with_local_address: bool,
    with_remote_address: bool,
    set_reuse_port: bool,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
    SO_REUSEPORT: int,
) -> None:
    # Arrange
    remote_address: tuple[str, int] | None = ("localhost", 12345) if with_remote_address else None
    local_address: tuple[str, int] | None = ("localhost", 11111) if with_local_address else None

    mock_getaddrinfo_side_effect: list[Any] = []
    if local_address is not None:
        mock_getaddrinfo_side_effect.append(datagram_addrinfo_list(local_address[1], [AF_INET]))
    if remote_address is not None:
        mock_getaddrinfo_side_effect.append(datagram_addrinfo_list(remote_address[1], [AF_INET]))
    mock_getaddrinfo.side_effect = mock_getaddrinfo_side_effect

    # Act
    socket = await create_datagram_socket(
        event_loop,
        family=AF_INET,
        local_address=local_address,
        remote_address=remote_address,
        reuse_port=set_reuse_port,
    )

    # Assert
    expected_await_args_list: list[Any] = []
    if local_address is not None:
        expected_flags = AI_PASSIVE if remote_address is None else 0
        expected_await_args_list.append(
            mocker.call(*local_address, family=AF_INET, type=SOCK_DGRAM, proto=0, flags=expected_flags)
        )
    if remote_address is not None:
        expected_await_args_list.append(mocker.call(*remote_address, family=AF_INET, type=SOCK_DGRAM, proto=0, flags=0))
    assert mock_getaddrinfo.await_args_list == expected_await_args_list

    mock_socket_cls.assert_called_once_with(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
    assert socket is mock_socket_ipv4

    mock_socket_ipv4.setblocking.assert_called_once_with(False)
    if set_reuse_port:
        mock_socket_ipv4.setsockopt.assert_any_call(SOL_SOCKET, SO_REUSEPORT, True)
    if local_address is None:
        mock_socket_ipv4.bind.assert_not_called()
    else:
        mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 11111))
    if remote_address is None:
        mock_sock_connect.assert_not_called()
    else:
        mock_sock_connect.assert_awaited_once_with(mock_socket_ipv4, ("127.0.0.1", 12345))
    mock_socket_ipv4.close.assert_not_called()

    mock_socket_ipv6.setblocking.assert_not_called()
    mock_socket_ipv6.bind.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_datagram_socket____first_failed(
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
    remote_address: tuple[str, int] = ("localhost", 12345)
    local_address: tuple[str, int] = ("localhost", 11111)

    mock_getaddrinfo.side_effect = [
        datagram_addrinfo_list(local_address[1]),
        datagram_addrinfo_list(remote_address[1]),
    ]

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
    socket = await create_datagram_socket(
        event_loop,
        local_address=local_address,
        remote_address=remote_address,
    )

    # Assert
    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET, SOCK_DGRAM, IPPROTO_UDP),
        mocker.call(AF_INET6, SOCK_DGRAM, IPPROTO_UDP),
    ]
    assert socket is mock_socket_ipv6

    if fail_on != "socket":
        mock_socket_ipv4.setblocking.assert_called_once_with(False)
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
    mock_socket_ipv6.bind.assert_called_once_with(("::1", 11111, 0, 0))
    if remote_address is not None:
        mock_sock_connect.assert_awaited_with(mock_socket_ipv6, ("::1", 12345, 0, 0))
    mock_socket_ipv6.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_datagram_socket____all_failed(
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
    remote_address: tuple[str, int] = ("localhost", 12345)
    local_address: tuple[str, int] = ("localhost", 11111)

    mock_getaddrinfo.side_effect = [
        datagram_addrinfo_list(local_address[1]),
        datagram_addrinfo_list(remote_address[1]),
    ]

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
        await create_datagram_socket(
            event_loop,
            local_address=local_address,
            remote_address=remote_address,
        )

    # Assert
    os_errors, exc = exc_info.value.split(OSError)
    assert exc is None
    assert os_errors is not None
    assert len(os_errors.exceptions) == 2
    assert all(isinstance(exc, OSError) for exc in os_errors.exceptions)
    del os_errors

    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET, SOCK_DGRAM, IPPROTO_UDP),
        mocker.call(AF_INET6, SOCK_DGRAM, IPPROTO_UDP),
    ]

    if fail_on != "socket":
        mock_socket_ipv4.setblocking.assert_called_once_with(False)
        mock_socket_ipv6.setblocking.assert_called_once_with(False)
        mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 11111))
        mock_socket_ipv6.bind.assert_called_once_with(("::1", 11111, 0, 0))
        match fail_on:
            case "bind":
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
@pytest.mark.usefixtures("remove_SO_REUSEPORT_support")
async def test____create_datagram_socket____SO_REUSEPORT_not_supported(
    event_loop: asyncio.AbstractEventLoop,
    mock_socket_ipv4: MagicMock,
    mock_getaddrinfo: AsyncMock,
) -> None:
    # Arrange
    local_host, local_port = "localhost", 11111

    mock_getaddrinfo.side_effect = [datagram_addrinfo_list(local_port)]

    # Act
    with pytest.raises(ValueError):
        await create_datagram_socket(event_loop, local_address=(local_host, local_port), reuse_port=True)

    # Assert
    mock_socket_ipv4.close.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "bind"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_datagram_socket____unrelated_exception(
    event_loop: asyncio.AbstractEventLoop,
    fail_on: Literal["socket", "bind"],
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_getaddrinfo: AsyncMock,
) -> None:
    # Arrange
    local_host, local_port = "localhost", 11111

    mock_getaddrinfo.side_effect = [datagram_addrinfo_list(local_port)]
    expected_failure_exception = BaseException()

    match fail_on:
        case "socket":
            mock_socket_cls.side_effect = expected_failure_exception
        case "bind":
            mock_socket_ipv4.bind.side_effect = expected_failure_exception
        case _:
            assert_never(fail_on)

    # Act
    with pytest.raises(BaseException) as exc_info:
        await create_datagram_socket(event_loop, local_address=(local_host, local_port))

    # Assert
    assert exc_info.value is expected_failure_exception
    if fail_on != "socket":
        mock_socket_ipv4.close.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["remote_address", "local_address"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_datagram_socket____getaddrinfo_returned_empty_list(
    event_loop: asyncio.AbstractEventLoop,
    fail_on: Literal["remote_address", "local_address"],
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
) -> None:
    # Arrange
    remote_address: tuple[str, int] = ("localhost", 12345)
    local_address: tuple[str, int] = ("localhost", 11111)

    match fail_on:
        case "remote_address":
            mock_getaddrinfo.side_effect = [datagram_addrinfo_list(local_address[1]), []]
        case "local_address":
            mock_getaddrinfo.side_effect = [[]]
        case _:
            assert_never(fail_on)

    # Act
    with pytest.raises(OSError, match=r"^getaddrinfo\('localhost'\) returned empty list$"):
        await create_datagram_socket(
            event_loop,
            local_address=local_address,
            remote_address=remote_address,
        )

    # Assert
    mock_socket_cls.assert_not_called()
    mock_socket_ipv4.bind.assert_not_called()
    mock_socket_ipv6.bind.assert_not_called()
    mock_sock_connect.assert_not_called()


@pytest.mark.asyncio
async def test____create_datagram_socket____getaddrinfo_return_mismatch(
    event_loop: asyncio.AbstractEventLoop,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
) -> None:
    # Arrange
    remote_address: tuple[str, int] = ("localhost", 12345)
    local_address: tuple[str, int] = ("localhost", 11111)

    mock_getaddrinfo.side_effect = [
        datagram_addrinfo_list(local_address[1], families=[AF_INET]),
        datagram_addrinfo_list(remote_address[1], families=[AF_INET6]),
    ]

    # Act
    with pytest.raises(OSError, match=r"^No matching local/remote pair according to family and proto found$"):
        await create_datagram_socket(
            event_loop,
            local_address=local_address,
            remote_address=remote_address,
        )

    # Assert
    mock_socket_cls.assert_not_called()
    mock_socket_ipv4.bind.assert_not_called()
    mock_socket_ipv6.bind.assert_not_called()
    mock_sock_connect.assert_not_called()


@pytest.mark.asyncio
async def test____create_datagram_socket____only_family____no_directives(
    event_loop: asyncio.AbstractEventLoop,
    mock_socket_cls: MagicMock,
) -> None:
    # Arrange

    # Act
    with pytest.raises(ValueError, match=r"^unexpected address family$"):
        await create_datagram_socket(event_loop)

    # Assert
    mock_socket_cls.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("remove_SO_REUSEPORT_support")
async def test____create_datagram_socket____only_family____SO_REUSEPORT_not_supported(
    event_loop: asyncio.AbstractEventLoop,
    mock_socket_ipv4: MagicMock,
    mock_socket_cls: MagicMock,
) -> None:
    # Arrange
    mock_socket_cls.side_effect = [mock_socket_ipv4]

    # Act
    with pytest.raises(ValueError):
        await create_datagram_socket(event_loop, family=AF_INET, reuse_port=True)

    # Assert
    mock_socket_cls.assert_called_once_with(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
    mock_socket_ipv4.close.assert_called_once_with()


@pytest.fixture
def addrinfo_list() -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    return (
        (AF_INET, SOCK_STREAM, IPPROTO_TCP, "", ("0.0.0.0", 65432)),
        (AF_INET6, SOCK_STREAM, IPPROTO_TCP, "", ("::", 65432, 0, 0)),
    )


@pytest.mark.parametrize("reuse_address", [False, True], ids=lambda boolean: f"reuse_address=={boolean}")
@pytest.mark.parametrize("SO_REUSEADDR_available", [False, True], ids=lambda boolean: f"SO_REUSEADDR_available=={boolean}")
@pytest.mark.parametrize("reuse_port", [False, True], ids=lambda boolean: f"reuse_port=={boolean}")
def test____open_listener_sockets_from_getaddrinfo_result____create_listener_sockets(
    reuse_address: bool,
    SO_REUSEADDR_available: bool,
    reuse_port: bool,
    mock_socket_cls: MagicMock,
    mocker: MockerFixture,
    addrinfo_list: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
    monkeypatch: pytest.MonkeyPatch,
    SO_REUSEPORT: int,
) -> None:
    # Arrange
    backlog: int = 123456
    if not SO_REUSEADDR_available:
        monkeypatch.delattr("socket.SO_REUSEADDR", raising=True)

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
    with pytest.raises(ExceptionGroup) as exc_info:
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
