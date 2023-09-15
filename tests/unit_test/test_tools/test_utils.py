from __future__ import annotations

import math
import os
import selectors
import ssl
import threading
from collections.abc import Callable
from socket import SO_ERROR, SOL_SOCKET
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.tools._utils import (
    check_real_socket_state,
    check_socket_family,
    check_socket_no_ssl,
    ensure_datagram_socket_bound,
    error_from_errno,
    is_ssl_eof_error,
    is_ssl_socket,
    iter_bytes,
    lock_with_timeout,
    make_callback,
    remove_traceback_frames_in_place,
    replace_kwargs,
    set_reuseport,
    transform_future_exception,
    validate_timeout_delay,
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


def test____make_callback____build_no_arg_callable(mocker: MockerFixture) -> None:
    # Arrange
    stub = mocker.stub()
    stub.return_value = mocker.sentinel.ret_val

    # Act
    cb = make_callback(stub, mocker.sentinel.arg1, mocker.sentinel.arg2, kw1=mocker.sentinel.kw1, kw2=mocker.sentinel.kw2)

    # Assert
    assert cb() is mocker.sentinel.ret_val
    stub.assert_called_once_with(mocker.sentinel.arg1, mocker.sentinel.arg2, kw1=mocker.sentinel.kw1, kw2=mocker.sentinel.kw2)


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


def test____check_real_socket_state____closed_socket(mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
    # Arrange
    mock_tcp_socket.fileno.return_value = -1
    mock_error_from_errno = mocker.patch(f"{error_from_errno.__module__}.{error_from_errno.__qualname__}")

    # Act
    check_real_socket_state(mock_tcp_socket)

    # Assert
    mock_tcp_socket.getsockopt.assert_not_called()
    mock_error_from_errno.assert_not_called()


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


@pytest.mark.parametrize("delay", [1, 3.14, math.inf])
@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
def test____validate_timeout_delay____positive_value(delay: float, positive_check: bool) -> None:
    # Arrange

    # Act & Assert
    assert validate_timeout_delay(delay, positive_check=positive_check) == delay


@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
def test____validate_timeout_delay____null_value(positive_check: bool) -> None:
    # Arrange
    delay: float = 0.0

    # Act & Assert
    assert validate_timeout_delay(delay, positive_check=positive_check) == delay


@pytest.mark.parametrize("delay", [-1, -3.14, -math.inf])
@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
def test____validate_timeout_delay____negative_value(delay: float, positive_check: bool) -> None:
    # Arrange

    # Act & Assert
    if positive_check:
        with pytest.raises(ValueError, match=r"^Invalid delay: negative value$"):
            validate_timeout_delay(delay, positive_check=positive_check)
    else:
        assert validate_timeout_delay(delay, positive_check=positive_check) == delay


@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
def test____validate_timeout_delay____not_a_number(positive_check: bool) -> None:
    # Arrange
    delay: float = math.nan

    # Act & Assert
    with pytest.raises(ValueError, match=r"^Invalid delay: NaN \(not a number\)$"):
        validate_timeout_delay(delay, positive_check=positive_check)


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
    mock_udp_socket.bind.assert_called_once_with(("localhost", 0))


def test____ensure_datagram_socket_bound____socket_not_bound____EINVAL_error_when_calling_getsockname(
    mock_udp_socket: MagicMock,
) -> None:
    # Arrange
    from errno import EINVAL

    mock_udp_socket.getsockname.side_effect = OSError(EINVAL, os.strerror(EINVAL))

    # Act
    ensure_datagram_socket_bound(mock_udp_socket)

    # Assert
    mock_udp_socket.bind.assert_called_once_with(("localhost", 0))


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
    SO_REUSEPORT: int,
) -> None:
    # Arrange
    mock_tcp_socket.setsockopt.return_value = None

    # Act
    set_reuseport(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_REUSEPORT, True)


@pytest.mark.usefixtures("remove_SO_REUSEPORT_support")
def test____set_reuseport____not_supported____not_defined(
    mock_tcp_socket: MagicMock,
) -> None:
    # Arrange
    mock_tcp_socket.setsockopt.side_effect = OSError

    # Act
    with pytest.raises(ValueError, match=r"^reuse_port not supported by socket module$"):
        set_reuseport(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_not_called()


def test____set_reuseport____not_supported____defined_but_not_implemented(
    mock_tcp_socket: MagicMock,
    SO_REUSEPORT: int,
) -> None:
    # Arrange
    mock_tcp_socket.setsockopt.side_effect = OSError

    # Act
    with pytest.raises(
        ValueError, match=r"^reuse_port not supported by socket module, SO_REUSEPORT defined but not implemented\.$"
    ):
        set_reuseport(mock_tcp_socket)

    # Assert
    mock_tcp_socket.setsockopt.assert_called_once_with(SOL_SOCKET, SO_REUSEPORT, True)


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


@pytest.mark.parametrize("n", [-1, 0, 2, 2000])
def test____remove_traceback_frames_in_place____remove_n_first_traceback(n: int) -> None:
    # Arrange
    import traceback

    def inner_func() -> None:
        raise Exception()

    def func() -> None:
        inner_func()

    # Act
    exception = pytest.raises(Exception, func).value
    assert len(list(traceback.walk_tb(exception.__traceback__))) == 3
    _returned_exception = remove_traceback_frames_in_place(exception, n)

    # Assert
    assert _returned_exception is exception
    if 0 <= n <= 3:
        assert len(list(traceback.walk_tb(exception.__traceback__))) == 3 - n
    elif n < 0:
        assert len(list(traceback.walk_tb(exception.__traceback__))) == 3
    else:  # n > 3
        assert len(list(traceback.walk_tb(exception.__traceback__))) == 0


def test____lock_with_timeout____acquire_and_release_with_timeout_at_None() -> None:
    # Arrange
    lock = threading.Lock()

    # Act & Assert
    assert not lock.locked()
    with lock_with_timeout(lock, None) as timeout:
        assert timeout is None
        assert lock.locked()
    assert not lock.locked()


def test____lock_with_timeout____acquire_and_release_with_timeout_value() -> None:
    # Arrange
    lock = threading.Lock()

    # Act & Assert
    assert not lock.locked()
    with lock_with_timeout(lock, 1.0) as timeout:
        assert timeout is not None and timeout == pytest.approx(1.0, rel=1e-1)
        assert lock.locked()
    assert not lock.locked()


def test____lock_with_timeout____acquire_and_release_with_timeout_value____timeout_error() -> None:
    # Arrange
    lock = threading.Lock()

    # Act & Assert
    lock.acquire()
    assert lock.locked()
    with pytest.raises(TimeoutError):
        with lock_with_timeout(lock, 1.0):
            pytest.fail("This should timeout.")


def test____lock_with_timeout____acquire_and_release_with_timeout_value____null_timeout() -> None:
    # Arrange
    lock = threading.Lock()

    # Act & Assert
    lock.acquire()
    assert lock.locked()
    with pytest.raises(TimeoutError):
        with lock_with_timeout(lock, 0):
            pytest.fail("This should timeout.")
