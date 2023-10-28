from __future__ import annotations

import contextlib
import math
import os
import ssl
import threading
from collections.abc import Callable
from errno import EINVAL, ENOTCONN, errorcode as errno_errorcode
from socket import SO_ERROR, SOL_SOCKET
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import BusyResourceError
from easynetwork.lowlevel._utils import (
    ResourceGuard,
    check_real_socket_state,
    check_socket_family,
    check_socket_is_connected,
    check_socket_no_ssl,
    ensure_datagram_socket_bound,
    error_from_errno,
    exception_with_notes,
    is_socket_connected,
    is_ssl_eof_error,
    is_ssl_socket,
    iter_bytes,
    lock_with_timeout,
    make_callback,
    prepend_argument,
    remove_traceback_frames_in_place,
    replace_kwargs,
    set_reuseport,
    validate_timeout_delay,
)
from easynetwork.lowlevel.constants import NOT_CONNECTED_SOCKET_ERRNOS

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


def test____prepend_argument____add_positional_argument(mocker: MockerFixture) -> None:
    # Arrange
    stub = mocker.stub()
    stub.return_value = mocker.sentinel.ret_val

    # Act
    cb = prepend_argument(mocker.sentinel.first_arg)(stub)

    # Assert
    assert cb(mocker.sentinel.arg1, kw1=mocker.sentinel.kw1) is mocker.sentinel.ret_val
    stub.assert_called_once_with(mocker.sentinel.first_arg, mocker.sentinel.arg1, kw1=mocker.sentinel.kw1)


def test____prepend_argument____several_prepend(mocker: MockerFixture) -> None:
    # Arrange
    stub = mocker.stub()
    stub.return_value = mocker.sentinel.ret_val

    # Act
    @prepend_argument(mocker.sentinel.second_arg)
    @prepend_argument(mocker.sentinel.first_arg)
    def cb(*args: Any, **kwargs: Any) -> Any:
        return stub(*args, **kwargs)

    # Assert
    assert cb(mocker.sentinel.arg1, kw1=mocker.sentinel.kw1) is mocker.sentinel.ret_val
    stub.assert_called_once_with(
        mocker.sentinel.first_arg,
        mocker.sentinel.second_arg,
        mocker.sentinel.arg1,
        kw1=mocker.sentinel.kw1,
    )


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


def test____is_socket_connected____getpeername_returns(mock_tcp_socket: MagicMock) -> None:
    # Arrange
    mock_tcp_socket.getpeername.return_value = ("127.0.0.1", 12345)

    # Act & Assert
    assert is_socket_connected(mock_tcp_socket)


@pytest.mark.parametrize("errno", sorted(NOT_CONNECTED_SOCKET_ERRNOS), ids=errno_errorcode.__getitem__)
def test____is_socket_connected____getpeername_raises(mock_tcp_socket: MagicMock, errno: int) -> None:
    # Arrange
    mock_tcp_socket.getpeername.side_effect = OSError(errno, os.strerror(errno))

    # Act & Assert
    assert not is_socket_connected(mock_tcp_socket)


def test____is_socket_connected____getpeername_raises_OSError(mock_tcp_socket: MagicMock) -> None:
    # Arrange
    mock_tcp_socket.getpeername.side_effect = OSError("Error")

    # Act & Assert
    with pytest.raises(OSError):
        is_socket_connected(mock_tcp_socket)


@pytest.mark.parametrize("connected", [True, False])
def test____check_socket_is_connected____default(
    connected: bool,
    mock_tcp_socket: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_is_socket_connected = mocker.patch(f"{is_socket_connected.__module__}.is_socket_connected", return_value=connected)

    # Act & Assert
    with pytest.raises(OSError) if not connected else contextlib.nullcontext() as exc_info:
        check_socket_is_connected(mock_tcp_socket)

    # Assert
    mock_is_socket_connected.assert_called_once_with(mock_tcp_socket)
    if exc_info is not None:
        assert exc_info.value.errno == ENOTCONN


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
    with pytest.raises(ValueError, match=r"^A 'SOCK_DGRAM' socket is expected$"):
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


def test____exception_with_notes____one_note() -> None:
    # Arrange
    exception = Exception()
    note = "A note."

    # Act
    returned_exception = exception_with_notes(exception, note)

    # Assert
    assert returned_exception is exception
    assert exception.__notes__ == [note]


def test____exception_with_notes____several_notes() -> None:
    # Arrange
    exception = Exception()
    notes = ["A note.", "Another note.", "Third one."]

    # Act
    returned_exception = exception_with_notes(exception, notes)

    # Assert
    assert returned_exception is exception
    assert exception.__notes__ == list(notes)


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


def test____ResourceGuard____forbid_nested_contexts() -> None:
    # Arrange
    guard = ResourceGuard("guard message")

    # Act & Assert
    with guard, pytest.raises(BusyResourceError, match=r"^guard message$"):
        with guard:
            pass
