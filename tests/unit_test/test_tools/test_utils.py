# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import selectors
import ssl
from socket import (
    AF_INET,
    AF_INET6,
    IPPROTO_IPV6,
    IPPROTO_TCP,
    IPV6_V6ONLY,
    SO_ERROR,
    SO_KEEPALIVE,
    SO_REUSEADDR,
    SOCK_STREAM,
    SOL_SOCKET,
    TCP_NODELAY,
)
from typing import TYPE_CHECKING, Any, Callable, Literal, Sequence, cast

from easynetwork.tools._utils import (
    check_real_socket_state,
    check_socket_family,
    check_socket_no_ssl,
    concatenate_chunks,
    ensure_datagram_socket_bound,
    error_from_errno,
    is_ssl_eof_error,
    is_ssl_socket,
    iter_bytes,
    open_listener_sockets_from_getaddrinfo_result,
    recursively_clear_exception_traceback_frames,
    replace_kwargs,
    set_reuseport,
    set_tcp_keepalive,
    set_tcp_nodelay,
    transform_future_exception,
    wait_socket_available,
)

import pytest

from ..base import SUPPORTED_FAMILIES, UNSUPPORTED_FAMILIES

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_socket_cls(mock_tcp_socket_factory: Callable[[], MagicMock], mocker: MockerFixture) -> MagicMock:
    return mocker.patch("socket.socket", side_effect=lambda f, t, p: mock_tcp_socket_factory())


@pytest.fixture(params=list(SUPPORTED_FAMILIES))
def socket_family(request: Any) -> Any:
    import socket

    return getattr(socket, request.param)


@pytest.fixture
def addrinfo_list() -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    return (
        (AF_INET, SOCK_STREAM, IPPROTO_TCP, "", ("0.0.0.0", 65432)),
        (AF_INET6, SOCK_STREAM, IPPROTO_TCP, "", ("::", 65432, 0, 0)),
    )


def test____replace_kwargs____rename_keys() -> None:
    # Arrange
    kwargs = {"arg1": 4, "arg2": 12, "not_modified": "Yes"}

    # Act
    replace_kwargs(kwargs, {"arg1": "arg12000", "arg2": "something"})

    # Assert
    assert kwargs == {"arg12000": 4, "something": 12, "not_modified": "Yes"}


def test____replace_kwargs____ignore_missing_keys() -> None:
    # Arrange
    kwargs = {"arg1": 4, "not_modified": "Yes"}

    # Act
    replace_kwargs(kwargs, {"unknown": "something", "arg1": "arg12000"})

    # Assert
    assert kwargs == {"arg12000": 4, "not_modified": "Yes"}


def test____replace_kwargs____error_target_already_present() -> None:
    # Arrange
    kwargs = {"arg1": 4, "arg12000": "Yes"}

    # Act
    with pytest.raises(TypeError, match=r"^Cannot set 'arg1' to 'arg12000': 'arg12000' in dictionary$"):
        replace_kwargs(kwargs, {"arg1": "arg12000"})

    # Assert
    assert kwargs == {"arg1": 4, "arg12000": "Yes"}


def test____replace_kwargs____error_empty_key_dict() -> None:
    # Arrange
    kwargs = {"arg1": 4, "arg12000": "Yes"}

    # Act
    with pytest.raises(ValueError, match=r"^Empty key dict$"):
        replace_kwargs(kwargs, {})

    # Assert
    assert kwargs == {"arg1": 4, "arg12000": "Yes"}


def test____error_from_errno____returns_OSError(mocker: MockerFixture) -> None:
    # Arrange
    errno: int = 123456
    mock_strerror = mocker.patch("os.strerror", return_value="errno message")

    # Act
    exception = error_from_errno(errno)

    # Assert
    assert isinstance(exception, OSError)
    assert exception.errno == errno
    assert exception.strerror == "errno message"
    mock_strerror.assert_called_once_with(errno)


def test____check_real_socket_state____socket_without_error(mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
    # Arrange
    mock_tcp_socket.getsockopt.return_value = 0
    mock_error_from_errno = mocker.patch(f"{error_from_errno.__module__}.{error_from_errno.__qualname__}")

    # Act
    check_real_socket_state(mock_tcp_socket)

    # Assert
    mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)
    mock_error_from_errno.assert_not_called()


def test____check_real_socket_state____socket_with_error(mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
    # Arrange
    errno = 123456
    exception = OSError(errno, "errno message")
    mock_tcp_socket.getsockopt.return_value = errno
    mock_error_from_errno = mocker.patch(f"{error_from_errno.__module__}.{error_from_errno.__qualname__}", return_value=exception)

    # Act
    with pytest.raises(OSError) as exc_info:
        check_real_socket_state(mock_tcp_socket)

    # Assert
    assert exc_info.value is exception
    mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)
    mock_error_from_errno.assert_called_once_with(errno)


def test____check_socket_family____valid_family(socket_family: int) -> None:
    # Arrange

    # Act
    check_socket_family(socket_family)

    # Assert
    ## There is no exception


@pytest.mark.parametrize("socket_family", list(UNSUPPORTED_FAMILIES), indirect=True)
def test____check_socket_family____invalid_family(socket_family: int) -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(ValueError, match=r"^Only these families are supported: .+$"):
        check_socket_family(socket_family)


def test____is_ssl_socket____regular_socket(mock_socket_factory: Callable[[], MagicMock]) -> None:
    # Arrange
    mock_socket = mock_socket_factory()

    # Act & Assert
    assert not is_ssl_socket(mock_socket)


def test____is_ssl_socket____ssl_socket(mock_ssl_socket: MagicMock) -> None:
    # Arrange

    # Act & Assert
    assert is_ssl_socket(mock_ssl_socket)


@pytest.mark.usefixtures("simulate_no_ssl_module")
def test____is_ssl_socket____no_ssl_module(mock_ssl_socket: MagicMock) -> None:
    # Arrange

    # Act & Assert
    assert not is_ssl_socket(mock_ssl_socket)


def test____check_socket_no_ssl____regular_socket(mock_socket_factory: Callable[[], MagicMock]) -> None:
    # Arrange
    mock_socket = mock_socket_factory()

    # Act & Assert
    check_socket_no_ssl(mock_socket)


def test____check_socket_no_ssl____ssl_socket(mock_ssl_socket: MagicMock) -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(TypeError, match=r"^ssl\.SSLSocket instances are forbidden$"):
        check_socket_no_ssl(mock_ssl_socket)


def test____is_ssl_eof_error____SSLEOFError() -> None:
    # Arrange

    # Act & Assert
    assert is_ssl_eof_error(ssl.SSLEOFError())


def test____is_ssl_eof_error____SSLError_with_specific_mnemonic() -> None:
    # Arrange

    # Act & Assert
    assert is_ssl_eof_error(ssl.SSLError(ssl.SSL_ERROR_SSL, "UNEXPECTED_EOF_WHILE_READING"))


def test____is_ssl_eof_error____OSError() -> None:
    # Arrange

    # Act & Assert
    assert not is_ssl_eof_error(OSError())


@pytest.mark.usefixtures("simulate_no_ssl_module")
def test____is_ssl_eof_error____no_ssl_module() -> None:
    # Arrange

    # Act & Assert
    assert not is_ssl_eof_error(ssl.SSLEOFError())


@pytest.mark.parametrize(["event", "selector_event"], [("read", "EVENT_READ"), ("write", "EVENT_WRITE")])
@pytest.mark.parametrize("timeout", [10.2, 0, None], ids=lambda value: f"timeout=={value}")
@pytest.mark.parametrize("available", [True, False], ids=lambda value: f"available=={value}")
@pytest.mark.parametrize("use_PollSelector", [True, False], ids=lambda value: f"use_PollSelector=={value}")
def test____wait_socket_available____returns_boolean_if_available_or_not(
    mock_socket_factory: Callable[[], MagicMock],
    event: Literal["read", "write"],
    selector_event: str,
    timeout: float | None,
    available: bool,
    use_PollSelector: bool,
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    SELECTOR_EVENT: int = getattr(selectors, selector_event)
    mock_socket = mock_socket_factory()
    mock_selector = mocker.NonCallableMagicMock(spec=selectors.BaseSelector)
    mock_selector.__enter__.return_value = mock_selector
    if use_PollSelector:
        mock_selector_cls = mocker.patch("selectors.PollSelector", return_value=mock_selector, create=True)
    else:
        monkeypatch.delattr("selectors.PollSelector", raising=False)
        mock_selector_cls = mocker.patch("selectors.SelectSelector", return_value=mock_selector)
    mock_selector_register: MagicMock = mock_selector.register
    mock_selector_select: MagicMock = mock_selector.select
    if available:
        mock_selector_select.return_value = [selectors.SelectorKey(mock_socket, 1, SELECTOR_EVENT, None)]
    else:
        mock_selector_select.return_value = []

    # Act
    status = wait_socket_available(mock_socket, timeout, event)

    # Assert
    mock_selector_cls.assert_called_once_with()
    mock_selector_register.assert_called_once_with(mock_socket, SELECTOR_EVENT)
    mock_selector_select.assert_called_once_with(timeout)
    assert status == available


@pytest.mark.parametrize(["event", "selector_event"], [("read", "EVENT_READ"), ("write", "EVENT_WRITE")])
@pytest.mark.parametrize("timeout", [10.2, 0, None], ids=lambda value: f"timeout=={value}")
def test____wait_socket_available____invalid_file_descriptor(
    mock_socket_factory: Callable[[], MagicMock],
    event: Literal["read", "write"],
    selector_event: str,
    timeout: float | None,
    mocker: MockerFixture,
) -> None:
    # Arrange
    SELECTOR_EVENT: int = getattr(selectors, selector_event)
    mock_socket = mock_socket_factory()
    mock_selector = mocker.NonCallableMagicMock(spec=selectors.BaseSelector)
    mock_selector.__enter__.return_value = mock_selector
    mock_selector_cls = mocker.patch("selectors.PollSelector", return_value=mock_selector, create=True)
    mock_selector_register: MagicMock = mock_selector.register
    mock_selector_select: MagicMock = mock_selector.select
    mock_selector_register.side_effect = ValueError

    # Act
    status = wait_socket_available(mock_socket, timeout, event)

    # Assert
    mock_selector_cls.assert_called_once_with()
    mock_selector_register.assert_called_once_with(mock_socket, SELECTOR_EVENT)
    mock_selector_select.assert_not_called()
    assert status is True


@pytest.mark.parametrize(["event", "selector_event"], [("read", "EVENT_READ"), ("write", "EVENT_WRITE")])
@pytest.mark.parametrize("timeout", [10.2, 0, None], ids=lambda value: f"timeout=={value}")
def test____wait_socket_available____select_error(
    mock_socket_factory: Callable[[], MagicMock],
    event: Literal["read", "write"],
    selector_event: str,
    timeout: float | None,
    mocker: MockerFixture,
) -> None:
    # Arrange
    SELECTOR_EVENT: int = getattr(selectors, selector_event)
    mock_socket = mock_socket_factory()
    mock_selector = mocker.NonCallableMagicMock(spec=selectors.BaseSelector)
    mock_selector.__enter__.return_value = mock_selector
    mock_selector_cls = mocker.patch("selectors.PollSelector", return_value=mock_selector, create=True)
    mock_selector_register: MagicMock = mock_selector.register
    mock_selector_select: MagicMock = mock_selector.select
    mock_selector_select.side_effect = OSError

    # Act
    status = wait_socket_available(mock_socket, timeout, event)

    # Assert
    mock_selector_cls.assert_called_once_with()
    mock_selector_register.assert_called_once_with(mock_socket, SELECTOR_EVENT)
    mock_selector_select.assert_called_once_with(timeout)
    assert status is True


def test____concanetate_chunks____join_several_bytestrings() -> None:
    # Arrange
    to_join = [b"a", b"b", b"cd", b"", b"efgh"]
    expected_result = b"abcdefgh"

    # Act
    result = concatenate_chunks(to_join)

    # Assert
    assert result == expected_result


def test____iter_bytes____iterate_over_bytes_returning_one_byte() -> None:
    # Arrange
    to_split = b"abcd"
    expected_result = [b"a", b"b", b"c", b"d"]

    # Act
    result = list(iter_bytes(to_split))

    # Assert
    assert result == expected_result


def test____ensure_datagram_socket_bound____socket_not_bound____null_port(
    mock_udp_socket: MagicMock,
) -> None:
    # Arrange
    mock_udp_socket.getsockname.return_value = ("0.0.0.0", 0)

    # Act
    ensure_datagram_socket_bound(mock_udp_socket)

    # Assert
    mock_udp_socket.bind.assert_called_once_with(("", 0))


def test____ensure_datagram_socket_bound____socket_not_bound____EINVAL_error_when_calling_getsockname(
    mock_udp_socket: MagicMock,
) -> None:
    # Arrange
    from errno import EINVAL

    mock_udp_socket.getsockname.side_effect = OSError(EINVAL, os.strerror(EINVAL))

    # Act
    ensure_datagram_socket_bound(mock_udp_socket)

    # Assert
    mock_udp_socket.bind.assert_called_once_with(("", 0))


def test____ensure_datagram_socket_bound____already_bound(
    mock_udp_socket: MagicMock,
) -> None:
    # Arrange
    mock_udp_socket.getsockname.return_value = ("0.0.0.0", 5000)

    # Act
    ensure_datagram_socket_bound(mock_udp_socket)

    # Assert
    mock_udp_socket.bind.assert_not_called()


def test____ensure_datagram_socket_bound____OSError(
    mock_udp_socket: MagicMock,
) -> None:
    # Arrange
    mock_udp_socket.getsockname.side_effect = OSError("Error")

    # Act
    with pytest.raises(OSError):
        ensure_datagram_socket_bound(mock_udp_socket)

    # Assert
    mock_udp_socket.bind.assert_not_called()


def test____ensure_datagram_socket_bound____invalid_socket_type(
    mock_tcp_socket: MagicMock,
) -> None:
    # Arrange

    # Act
    with pytest.raises(ValueError, match=r"^Invalid socket type\. Expected SOCK_DGRAM socket\.$"):
        ensure_datagram_socket_bound(mock_tcp_socket)

    # Assert
    mock_tcp_socket.getsockname.assert_not_called()
    mock_tcp_socket.bind.assert_not_called()


def test____set_reuseport____setsockopt(
    mock_tcp_socket: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    SO_REUSEPORT: int = 123456
    mock_tcp_socket.setsockopt.return_value = None
    monkeypatch.setattr("socket.SO_REUSEPORT", SO_REUSEPORT, raising=False)

    # Act
    set_reuseport(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_REUSEPORT, True)


def test____set_reuseport____not_supported____not_defined(
    mock_tcp_socket: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    mock_tcp_socket.setsockopt.side_effect = OSError
    monkeypatch.delattr("socket.SO_REUSEPORT", raising=False)

    # Act
    with pytest.raises(ValueError, match=r"^reuse_port not supported by socket module$"):
        set_reuseport(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_not_called()


def test____set_reuseport____not_supported____defined_but_not_implemented(
    mock_tcp_socket: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    SO_REUSEPORT: int = 123456
    mock_tcp_socket.setsockopt.side_effect = OSError
    monkeypatch.setattr("socket.SO_REUSEPORT", SO_REUSEPORT, raising=False)

    # Act
    with pytest.raises(
        ValueError, match=r"^reuse_port not supported by socket module, SO_REUSEPORT defined but not implemented\.$"
    ):
        set_reuseport(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_REUSEPORT, True)


def test____set_tcp_nodelay____setsockopt(
    mock_tcp_socket: MagicMock,
) -> None:
    # Arrange

    # Act
    set_tcp_nodelay(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_called_once_with(IPPROTO_TCP, TCP_NODELAY, True)


def test____set_tcp_keepalive____setsockopt(
    mock_tcp_socket: MagicMock,
) -> None:
    # Arrange

    # Act
    set_tcp_keepalive(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_KEEPALIVE, True)


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
) -> None:
    # Arrange
    SO_REUSEPORT: int = 123456
    monkeypatch.setattr("socket.SO_REUSEPORT", SO_REUSEPORT, raising=False)
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
    assert mock_socket_cls.mock_calls == [mocker.call(f, t, p) for f, t, p, _, _ in addrinfo_list]
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


def test____transform_future_exception____keep_common_exception_as_is() -> None:
    # Arrange
    exception = BaseException()

    # Act
    new_exception = transform_future_exception(exception)

    # Assert
    assert new_exception is exception


@pytest.mark.parametrize("exception", [SystemExit(0), KeyboardInterrupt()], ids=lambda f: type(f).__name__)
def test____transform_future_exception____make_cancelled_error_from_exception(exception: BaseException) -> None:
    # Arrange
    from concurrent.futures import CancelledError

    # Act
    new_exception = transform_future_exception(exception)

    # Assert
    assert type(new_exception) is CancelledError
    assert new_exception.__cause__ is exception
    assert new_exception.__context__ is exception
    assert new_exception.__suppress_context__


def test____recursively_clear_exception_traceback_frames____exception_without_context_nor_cause(
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_clear_frames = mocker.patch("traceback.clear_frames", autospec=True)

    def func() -> None:
        raise Exception()

    # Act
    exception = pytest.raises(Exception, func).value
    assert exception.__context__ is None and exception.__cause__ is None
    recursively_clear_exception_traceback_frames(exception)

    # Assert
    mock_clear_frames.assert_called_once_with(exception.__traceback__)


def test____recursively_clear_exception_traceback_frames____exception_with_context_but_no_explicit_cause(
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_clear_frames = mocker.patch("traceback.clear_frames", autospec=True)

    def func() -> None:
        try:
            1 / 0
        except ZeroDivisionError:
            raise Exception()

    # Act
    exception = pytest.raises(Exception, func).value
    assert isinstance(exception.__context__, ZeroDivisionError)
    assert exception.__cause__ is None
    recursively_clear_exception_traceback_frames(exception)

    # Assert
    assert mock_clear_frames.mock_calls == [
        mocker.call(exception.__traceback__),
        mocker.call(exception.__context__.__traceback__),
    ]


def test____recursively_clear_exception_traceback_frames____exception_with_explicit_cause(
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_clear_frames = mocker.patch("traceback.clear_frames", autospec=True)

    def func() -> None:
        try:
            1 / 0
        except ZeroDivisionError as exc:
            raise Exception() from exc

    # Act
    exception = pytest.raises(Exception, func).value
    assert isinstance(exception.__context__, ZeroDivisionError)
    assert exception.__cause__ is exception.__context__
    recursively_clear_exception_traceback_frames(exception)

    # Assert
    assert mock_clear_frames.mock_calls == [
        mocker.call(exception.__traceback__),
        mocker.call(exception.__context__.__traceback__),
    ]


def test____recursively_clear_exception_traceback_frames____exception_with_context_but_different_cause(
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_clear_frames = mocker.patch("traceback.clear_frames", autospec=True)

    def func() -> None:
        try:
            1 / 0
        except ZeroDivisionError as exc:
            try:
                raise ValueError()
            except ValueError:
                raise Exception() from exc

    # Act
    exception = pytest.raises(Exception, func).value
    assert isinstance(exception.__context__, ValueError)
    assert isinstance(exception.__context__.__context__, ZeroDivisionError)
    assert exception.__context__.__cause__ is None
    assert isinstance(exception.__cause__, ZeroDivisionError)
    recursively_clear_exception_traceback_frames(exception)

    # Assert
    assert mock_clear_frames.mock_calls == [
        mocker.call(exception.__traceback__),
        mocker.call(exception.__context__.__traceback__),
        mocker.call(exception.__context__.__context__.__traceback__),
        mocker.call(exception.__cause__.__traceback__),
    ]
