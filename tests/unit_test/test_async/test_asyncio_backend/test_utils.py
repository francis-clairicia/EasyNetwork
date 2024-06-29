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
    IPPROTO_TCP,
    IPPROTO_UDP,
    SOCK_DGRAM,
    SOCK_STREAM,
    SocketType,
    gaierror,
)
from typing import TYPE_CHECKING, Any, Literal, Protocol as TypingProtocol, assert_never

from easynetwork.lowlevel._utils import error_from_errno
from easynetwork.lowlevel.api_async.backend._asyncio._asyncio_utils import (
    create_connection,
    create_datagram_connection,
    ensure_resolved,
    wait_until_readable,
    wait_until_writable,
)
from easynetwork.lowlevel.api_async.backend._asyncio.tasks import TaskUtils

import pytest

from ....tools import is_proactor_event_loop
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
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    expected_result = stream_addrinfo_list(8080, families=[AF_INET])
    mock_stdlib_socket_getaddrinfo.return_value = expected_result

    # Act
    info = await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, proto=IPPROTO_TCP, flags=AI_PASSIVE)

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
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    mock_stdlib_socket_getaddrinfo.return_value = []

    # Act
    with pytest.raises(OSError, match=r"^getaddrinfo\('127.0.0.1'\) returned empty list$"):
        await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, proto=IPPROTO_TCP, flags=AI_PASSIVE)

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
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    expected_result = stream_addrinfo_list(8080, families=[AF_INET])
    mock_stdlib_socket_getaddrinfo.side_effect = gaierror(EAI_NONAME, "Name or service not known")
    mock_getaddrinfo.return_value = expected_result

    # Act
    info = await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, proto=IPPROTO_TCP, flags=AI_PASSIVE)

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
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    mock_stdlib_socket_getaddrinfo.side_effect = gaierror(EAI_NONAME, "Name or service not known")
    mock_getaddrinfo.return_value = []

    # Act
    with pytest.raises(OSError, match=r"^getaddrinfo\('127.0.0.1'\) returned empty list$"):
        await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, proto=IPPROTO_TCP, flags=AI_PASSIVE)

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
    mock_getaddrinfo: AsyncMock,
    mock_stdlib_socket_getaddrinfo: MagicMock,
) -> None:
    # Arrange
    mock_stdlib_socket_getaddrinfo.side_effect = gaierror(EAI_BADFLAGS, "Invalid flags")

    # Act
    with pytest.raises(gaierror):
        await ensure_resolved("127.0.0.1", 8080, 123456789, SOCK_STREAM, proto=IPPROTO_TCP, flags=AI_PASSIVE)

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


class _CreateConnectionCallable(TypingProtocol):
    async def __call__(
        self,
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
def create_connection_of_socktype(connection_socktype: int) -> _CreateConnectionCallable:
    if connection_socktype == SOCK_STREAM:
        return create_connection
    if connection_socktype == SOCK_DGRAM:
        return create_datagram_connection
    pytest.fail("Invalid fixture argument")


@pytest.fixture
def addrinfo_list_factory(connection_socktype: int) -> _AddrInfoListFactory:
    if connection_socktype == SOCK_STREAM:
        return stream_addrinfo_list
    if connection_socktype == SOCK_DGRAM:
        return datagram_addrinfo_list
    pytest.fail("Invalid fixture argument")


@pytest.mark.asyncio
@pytest.mark.parametrize("with_local_address", [False, True], ids=lambda boolean: f"with_local_address=={boolean}")
async def test____create_connection____default(
    create_connection_of_socktype: _CreateConnectionCallable,
    addrinfo_list_factory: _AddrInfoListFactory,
    connection_socktype: int,
    with_local_address: bool,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    expected_proto = IPPROTO_TCP if connection_socktype == SOCK_STREAM else IPPROTO_UDP
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] | None = ("localhost", 11111) if with_local_address else None

    if local_address is None:
        mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port)]
    else:
        mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port), addrinfo_list_factory(local_address[1])]

    # Act
    socket = await create_connection_of_socktype(remote_host, remote_port, local_address=local_address)

    # Assert
    if local_address is None:
        assert mock_getaddrinfo.await_args_list == [
            mocker.call(remote_host, remote_port, family=AF_UNSPEC, type=connection_socktype, proto=0, flags=0),
        ]
    else:
        assert mock_getaddrinfo.await_args_list == [
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
    mock_sock_connect.assert_awaited_once_with(mock_socket_ipv6, ("::1", 12345, 0, 0))
    mock_socket_ipv6.close.assert_not_called()

    mock_socket_ipv4.setblocking.assert_not_called()
    mock_socket_ipv4.bind.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____first_failed(
    fail_on: Literal["socket", "bind", "connect"],
    create_connection_of_socktype: _CreateConnectionCallable,
    addrinfo_list_factory: _AddrInfoListFactory,
    connection_socktype: int,
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
        mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port)]
    else:
        mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port), addrinfo_list_factory(local_address[1])]

    match fail_on:
        case "socket":
            mock_socket_cls.side_effect = [error_from_errno(errno.EAFNOSUPPORT), mock_socket_ipv4]
        case "bind":
            mock_socket_ipv6.bind.side_effect = error_from_errno(errno.EADDRINUSE)
        case "connect":
            mock_sock_connect.side_effect = [error_from_errno(errno.ECONNREFUSED), None]
        case _:
            assert_never(fail_on)

    # Act
    socket = await create_connection_of_socktype(remote_host, remote_port, local_address=local_address)

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
        mock_socket_ipv6.setblocking.assert_called_once_with(False)
        if local_address is None:
            mock_socket_ipv6.bind.assert_not_called()
        else:
            mock_socket_ipv6.bind.assert_called_once_with(("::1", 11111, 0, 0))
        match fail_on:
            case "bind":
                assert mocker.call(mock_socket_ipv6, ("::1", 12345, 0, 0)) not in mock_sock_connect.await_args_list
            case "connect":
                mock_sock_connect.assert_any_await(mock_socket_ipv6, ("::1", 12345, 0, 0))
            case _:
                assert_never(fail_on)
        mock_socket_ipv6.close.assert_called_once_with()

    mock_socket_ipv4.setblocking.assert_called_once_with(False)
    if local_address is None:
        mock_socket_ipv4.bind.assert_not_called()
    else:
        mock_socket_ipv4.bind.assert_called_once_with(("127.0.0.1", 11111))
    mock_sock_connect.assert_awaited_with(mock_socket_ipv4, ("127.0.0.1", 12345))
    mock_socket_ipv4.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["socket", "bind", "connect"], ids=lambda fail_on: f"fail_on=={fail_on}")
async def test____create_connection____all_failed(
    fail_on: Literal["socket", "bind", "connect"],
    create_connection_of_socktype: _CreateConnectionCallable,
    addrinfo_list_factory: _AddrInfoListFactory,
    connection_socktype: int,
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
        mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port)]
    else:
        mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port), addrinfo_list_factory(local_address[1])]

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
        await create_connection_of_socktype(remote_host, remote_port, local_address=local_address)

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
    fail_on: Literal["socket", "connect"],
    connection_socktype: int,
    create_connection_of_socktype: _CreateConnectionCallable,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345

    mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port)]
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
        await create_connection_of_socktype(remote_host, remote_port)

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
    create_connection_of_socktype: _CreateConnectionCallable,
    addrinfo_list_factory: _AddrInfoListFactory,
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
            mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port), []]
        case _:
            assert_never(fail_on)

    # Act
    with pytest.raises(OSError, match=r"^getaddrinfo\('localhost'\) returned empty list$"):
        await create_connection_of_socktype(remote_host, remote_port, local_address=local_address)

    # Assert
    mock_socket_cls.assert_not_called()
    mock_socket_ipv4.bind.assert_not_called()
    mock_socket_ipv6.bind.assert_not_called()
    mock_sock_connect.assert_not_called()


@pytest.mark.asyncio
async def test____create_connection____getaddrinfo_return_mismatch(
    create_connection_of_socktype: _CreateConnectionCallable,
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    local_address: tuple[str, int] = ("localhost", 11111)

    mock_getaddrinfo.side_effect = [
        addrinfo_list_factory(remote_port, families=[AF_INET6]),
        addrinfo_list_factory(local_address[1], families=[AF_INET]),
    ]

    # Act
    with pytest.raises(ExceptionGroup) as exc_info:
        await create_connection_of_socktype(remote_host, remote_port, local_address=local_address)

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
@pytest.mark.parametrize("connection_socktype", [SOCK_STREAM], indirect=True, ids=repr)
@pytest.mark.flaky(retries=3)
async def test____create_connection____happy_eyeballs_delay____connect_cancellation(
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    event_loop = asyncio.get_running_loop()
    timestamps: list[float] = []
    remote_host, remote_port = "localhost", 12345
    mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port, families=[AF_INET6, AF_INET])]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        timestamps.append(event_loop.time())
        if sock.family == AF_INET6:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.01)

    mock_sock_connect.side_effect = connect_side_effect

    # Act
    socket = await create_connection(remote_host, remote_port, happy_eyeballs_delay=0.5)

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
async def test____create_connection____happy_eyeballs_delay____connect_too_late(
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port, families=[AF_INET6, AF_INET])]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            TaskUtils.current_asyncio_task().uncancel()
            await asyncio.sleep(0)

    mock_sock_connect.side_effect = connect_side_effect

    # Act
    socket = await create_connection(remote_host, remote_port, happy_eyeballs_delay=0.25)

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
async def test____create_connection____happy_eyeballs_delay____winner_closed_because_of_exception_in_another_task(
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv4: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    expected_failure_exception = BaseException("error")
    remote_host, remote_port = "localhost", 12345
    mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port, families=[AF_INET6, AF_INET])]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise expected_failure_exception from None

    mock_sock_connect.side_effect = connect_side_effect

    # Act
    with pytest.raises(BaseExceptionGroup) as exc_info:
        await create_connection(remote_host, remote_port, happy_eyeballs_delay=0.25)

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
async def test____create_connection____happy_eyeballs_delay____addrinfo_reordering____prioritize_ipv6_over_ipv4(
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    mock_getaddrinfo.side_effect = [addrinfo_list_factory(remote_port, families=[AF_INET, AF_INET6])]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        await asyncio.sleep(0.5)

    mock_sock_connect.side_effect = connect_side_effect

    # Act
    socket = await create_connection(remote_host, remote_port, happy_eyeballs_delay=0.25)

    # Assert
    assert socket is mock_socket_ipv6
    assert mock_socket_cls.call_args_list == [
        mocker.call(AF_INET6, SOCK_STREAM, IPPROTO_TCP),
        mocker.call(AF_INET, SOCK_STREAM, IPPROTO_TCP),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_socktype", [SOCK_STREAM], indirect=True, ids=repr)
async def test____create_connection____happy_eyeballs_delay____addrinfo_reordering____interleave_families(
    addrinfo_list_factory: _AddrInfoListFactory,
    mock_socket_cls: MagicMock,
    mock_socket_ipv6: MagicMock,
    mock_getaddrinfo: AsyncMock,
    mock_sock_connect: AsyncMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    remote_host, remote_port = "localhost", 12345
    mock_getaddrinfo.side_effect = [
        addrinfo_list_factory(remote_port, families=[AF_INET6, AF_INET6, AF_INET6, AF_INET, AF_INET, AF_INET]),
    ]

    async def connect_side_effect(sock: SocketType, address: tuple[Any, ...]) -> None:
        await asyncio.sleep(1)

    mock_sock_connect.side_effect = connect_side_effect

    # Act
    socket = await create_connection(remote_host, remote_port, happy_eyeballs_delay=0.1)

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
@pytest.mark.parametrize(
    ["waiter", "event_loop_add_event_func_name", "event_loop_remove_event_func_name"],
    [
        pytest.param(wait_until_readable, "add_reader", "remove_reader", id="read"),
        pytest.param(wait_until_writable, "add_writer", "remove_writer", id="write"),
    ],
)
@pytest.mark.parametrize("future_cancelled", [False, True], ids=lambda p: f"future_cancelled=={p}")
async def test____wait_until___event_wakeup(
    waiter: Callable[[SocketType, asyncio.AbstractEventLoop], asyncio.Future[None]],
    event_loop_add_event_func_name: str,
    event_loop_remove_event_func_name: str,
    future_cancelled: bool,
    mock_socket_factory: Callable[[], MagicMock],
    mocker: MockerFixture,
) -> None:
    # Arrange
    event_loop = asyncio.get_running_loop()
    if is_proactor_event_loop(event_loop):
        pytest.skip(f"event_loop.{event_loop_add_event_func_name}() is not supported on asyncio.ProactorEventLoop")

    event_loop_add_event = mocker.patch.object(
        event_loop,
        event_loop_add_event_func_name,
        side_effect=lambda sock, cb, *args: event_loop.call_soon(cb, *args),
    )
    event_loop_remove_event = mocker.patch.object(event_loop, event_loop_remove_event_func_name)
    mock_socket = mock_socket_factory()

    # Act
    fut = waiter(mock_socket, event_loop)
    if future_cancelled:
        fut.cancel()
        await asyncio.sleep(0)
    else:
        await fut

    # Assert
    event_loop_add_event.assert_called_once_with(mock_socket, mocker.ANY, mocker.ANY)
    event_loop_remove_event.assert_called_once_with(mock_socket)
