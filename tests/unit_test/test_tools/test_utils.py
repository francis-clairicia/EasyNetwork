from __future__ import annotations

import contextlib
import dataclasses
import functools
import itertools
import math
import os
import ssl
import threading
import weakref
from collections import deque
from collections.abc import Callable
from errno import EADDRINUSE, EINVAL, ENOTCONN, errorcode as errno_errorcode
from socket import SO_ERROR, SOL_SOCKET
from typing import TYPE_CHECKING, Any, Literal, Protocol

from easynetwork.exceptions import BusyResourceError
from easynetwork.lowlevel._final import runtime_final_class
from easynetwork.lowlevel._utils import (
    ElapsedTime,
    Flag,
    ResourceGuard,
    adjust_leftover_buffer,
    check_inet_socket_family,
    check_real_socket_state,
    check_socket_is_connected,
    check_socket_no_ssl,
    convert_socket_bind_error,
    error_from_errno,
    exception_with_notes,
    get_callable_name,
    is_socket_connected,
    is_ssl_eof_error,
    is_ssl_socket,
    iter_bytes,
    iterate_exceptions,
    lock_with_timeout,
    make_callback,
    missing_extra_deps,
    prepend_argument,
    remove_traceback_frames_in_place,
    replace_kwargs,
    set_reuseport,
    supports_socket_sendmsg,
    validate_listener_hosts,
    validate_optional_timeout_delay,
    validate_timeout_delay,
    weak_method_proxy,
)
from easynetwork.lowlevel.constants import NOT_CONNECTED_SOCKET_ERRNOS

import pytest

from .._utils import unsupported_families
from ..base import INET_FAMILIES

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture(params=list(INET_FAMILIES))
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
    with pytest.raises(ValueError, match=r"^Cannot set 'arg1' to 'arg12000': 'arg12000' in dictionary$"):
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


@pytest.mark.parametrize("already_weak_method", [True, False], ids=lambda p: f"already_weak_method=={p}")
def test____weak_method_proxy_____wrap_method(already_weak_method: bool, mocker: MockerFixture) -> None:
    # Arrange
    @dataclasses.dataclass
    class MyObject:
        stub: MagicMock = dataclasses.field(default_factory=mocker.stub)

        def method(self, *args: Any, **kwargs: Any) -> Any:
            return self.stub(*args, **kwargs)

    obj = MyObject()
    obj.stub.return_value = mocker.sentinel.ret_val

    # Act
    cb: Callable[..., Any]
    if already_weak_method:
        cb = weak_method_proxy(weakref.WeakMethod(obj.method))
    else:
        cb = weak_method_proxy(obj.method)

    # Assert
    assert (
        cb(
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kw1,
            kw2=mocker.sentinel.kw2,
        )
        is mocker.sentinel.ret_val
    )
    obj.stub.assert_called_once_with(mocker.sentinel.arg1, mocker.sentinel.arg2, kw1=mocker.sentinel.kw1, kw2=mocker.sentinel.kw2)


def test____weak_method_proxy_____strong_reference_dropped(mocker: MockerFixture) -> None:
    # Arrange
    @dataclasses.dataclass
    class MyObject:
        stub: MagicMock = dataclasses.field(default_factory=mocker.stub)

        def method(self, *args: Any, **kwargs: Any) -> Any:
            return self.stub(*args, **kwargs)

    obj = MyObject()
    obj.stub.return_value = mocker.sentinel.ret_val

    # Act
    cb = weak_method_proxy(obj.method)

    # Assert
    del obj
    with pytest.raises(ReferenceError):
        _ = cb()


def test____prepend_argument____add_positional_argument____direct_call(mocker: MockerFixture) -> None:
    # Arrange
    stub = mocker.stub()
    stub.return_value = mocker.sentinel.ret_val

    # Act
    cb = prepend_argument(mocker.sentinel.first_arg, stub)

    # Assert
    assert cb(mocker.sentinel.arg1, kw1=mocker.sentinel.kw1) is mocker.sentinel.ret_val
    stub.assert_called_once_with(mocker.sentinel.first_arg, mocker.sentinel.arg1, kw1=mocker.sentinel.kw1)


def test____prepend_argument____add_positional_argument____decorator(mocker: MockerFixture) -> None:
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


@pytest.mark.parametrize("module", ["package.module", None], ids=lambda p: f"module=={p!r}")
def test____get_callable_name____qualname(module: str | None, mocker: MockerFixture) -> None:
    # Arrange
    func = mocker.stub()
    func.__name__ = "func"
    func.__qualname__ = "namespace.func"
    func.__module__ = module or ""

    # Act
    name = get_callable_name(func)

    # Assert
    if module:
        assert name == f"{module}.namespace.func"
    else:
        assert name == "namespace.func"


@pytest.mark.parametrize("module", ["package.module", None], ids=lambda p: f"module=={p!r}")
def test____get_callable_name____name_without_qualname(module: str | None, mocker: MockerFixture) -> None:
    # Arrange
    func = mocker.stub()
    func.__name__ = "func"
    del func.__qualname__
    func.__module__ = module or ""

    # Act
    name = get_callable_name(func)

    # Assert
    if module:
        assert name == f"{module}.func"
    else:
        assert name == "func"


@pytest.mark.parametrize("module", ["package.module", None], ids=lambda p: f"module=={p!r}")
def test____get_callable_name____neither_name_nor_qualname(module: str | None, mocker: MockerFixture) -> None:
    # Arrange
    func = mocker.stub()
    del func.__name__
    del func.__qualname__
    func.__module__ = module or ""

    # Act
    name = get_callable_name(func)

    # Assert
    assert name == ""


def test____get_callable_name____unwrap_partial(mocker: MockerFixture) -> None:
    # Arrange
    func = mocker.stub()
    func.__name__ = "func"
    func.__qualname__ = "namespace.func"
    func.__module__ = "package.module"

    # Act
    name = get_callable_name(functools.partial(func, mocker.sentinel.arg, kw=mocker.sentinel.kwarg))

    # Assert
    assert name == "package.module.namespace.func"


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


def test____error_from_errno____strerror_fmt(mocker: MockerFixture) -> None:
    # Arrange
    errno: int = 123456
    mock_strerror = mocker.patch("os.strerror", return_value="errno message")

    # Act
    exception = error_from_errno(errno, msg="{strerror} + custom message")

    # Assert
    assert isinstance(exception, OSError)
    assert exception.errno == errno
    assert exception.strerror == "errno message + custom message"
    mock_strerror.assert_called_once_with(errno)


def test____error_from_errno____custom_message_only(mocker: MockerFixture) -> None:
    # Arrange
    errno: int = 123456
    mock_strerror = mocker.patch("os.strerror", return_value="errno message")

    # Act
    exception = error_from_errno(errno, msg="custom message")

    # Assert
    assert isinstance(exception, OSError)
    assert exception.errno == errno
    assert exception.strerror == "custom message"
    mock_strerror.assert_called_once_with(errno)


def test____missing_extra_deps____returns_ModuleNotFoundError() -> None:
    # Arrange

    # Act
    exception = missing_extra_deps("cbor")

    # Assert
    assert isinstance(exception, ModuleNotFoundError)
    assert exception.args[0] == "cbor dependencies are missing. Consider adding 'cbor' extra"
    assert exception.__notes__ == ['example: pip install "easynetwork[cbor]"']


def test____missing_extra_deps____returns_ModuleNotFoundError____specify_feature_name() -> None:
    # Arrange

    # Act
    exception = missing_extra_deps("msgpack", feature_name="message-pack")

    # Assert
    assert isinstance(exception, ModuleNotFoundError)
    assert exception.args[0] == "message-pack dependencies are missing. Consider adding 'msgpack' extra"
    assert exception.__notes__ == ['example: pip install "easynetwork[msgpack]"']


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
    mock_error_from_errno = mocker.patch(
        f"{check_real_socket_state.__module__}.{error_from_errno.__qualname__}",
        return_value=exception,
    )

    # Act
    with pytest.raises(OSError) as exc_info:
        check_real_socket_state(mock_tcp_socket)

    # Assert
    assert exc_info.value is exception
    mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)
    mock_error_from_errno.assert_called_once_with(errno)


def test____check_real_socket_state____socket_with_error____custom_message(
    mock_tcp_socket: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    errno = 123456
    exception = OSError(errno, "errno message")
    mock_tcp_socket.getsockopt.return_value = errno
    mock_error_from_errno = mocker.patch(
        f"{check_real_socket_state.__module__}.{error_from_errno.__qualname__}",
        return_value=exception,
    )

    # Act
    with pytest.raises(OSError) as exc_info:
        check_real_socket_state(mock_tcp_socket, error_msg="unrelated error: {strerror}")

    # Assert
    assert exc_info.value is exception
    mock_tcp_socket.getsockopt.assert_called_once_with(SOL_SOCKET, SO_ERROR)
    mock_error_from_errno.assert_called_once_with(errno, "unrelated error: {strerror}")


def test____check_real_socket_state____closed_socket(mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
    # Arrange
    mock_tcp_socket.fileno.return_value = -1
    mock_error_from_errno = mocker.patch(f"{error_from_errno.__module__}.{error_from_errno.__qualname__}")

    # Act
    check_real_socket_state(mock_tcp_socket)

    # Assert
    mock_tcp_socket.getsockopt.assert_not_called()
    mock_error_from_errno.assert_not_called()


@pytest.mark.parametrize("socket_family", list(INET_FAMILIES), indirect=True)
def test____check_inet_socket_family____valid_family(socket_family: int) -> None:
    # Arrange

    # Act
    check_inet_socket_family(socket_family)

    # Assert
    ## There is no exception


@pytest.mark.parametrize("socket_family", list(unsupported_families(INET_FAMILIES)), indirect=True)
def test____check_inet_socket_family____invalid_family(socket_family: int) -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(ValueError, match=r"^Only these families are supported: AF_INET, AF_INET6$"):
        check_inet_socket_family(socket_family)


def test____supports_socket_sendmsg____have_sendmsg_method(
    mock_socket_factory: Callable[[], MagicMock],
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_socket = mock_socket_factory()
    mock_socket.sendmsg = mocker.MagicMock(
        spec=lambda *args: None,
        side_effect=lambda buffers, *args: sum(map(len, map(lambda v: memoryview(v), buffers))),
    )

    # Act & Assert
    assert supports_socket_sendmsg(mock_socket)


def test____supports_socket_sendmsg____dont_have_sendmsg_method(
    mock_socket_factory: Callable[[], MagicMock],
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_socket = mock_socket_factory()
    del mock_socket.sendmsg

    # Act & Assert
    assert not supports_socket_sendmsg(mock_socket)


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


class _validate_timeout_delay_func_type(Protocol):
    def __call__(self, /, delay: float, *, positive_check: bool) -> float:
        raise NotImplementedError


@pytest.mark.parametrize("delay", [1, 3.14, math.inf])
@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
@pytest.mark.parametrize("validator_func", [validate_timeout_delay, validate_optional_timeout_delay])
def test____validate_timeout_delay____positive_value(
    delay: float,
    positive_check: bool,
    validator_func: _validate_timeout_delay_func_type,
) -> None:
    # Arrange

    # Act & Assert
    assert validator_func(delay, positive_check=positive_check) == delay


@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
@pytest.mark.parametrize("validator_func", [validate_timeout_delay, validate_optional_timeout_delay])
def test____validate_timeout_delay____null_value(
    positive_check: bool,
    validator_func: _validate_timeout_delay_func_type,
) -> None:
    # Arrange
    delay: float = 0.0

    # Act & Assert
    assert validator_func(delay, positive_check=positive_check) == delay


@pytest.mark.parametrize("delay", [-1, -3.14, -math.inf])
@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
@pytest.mark.parametrize("validator_func", [validate_timeout_delay, validate_optional_timeout_delay])
def test____validate_timeout_delay____negative_value(
    delay: float,
    positive_check: bool,
    validator_func: _validate_timeout_delay_func_type,
) -> None:
    # Arrange

    # Act & Assert
    if positive_check:
        with pytest.raises(ValueError, match=r"^Invalid delay: negative value$"):
            validator_func(delay, positive_check=positive_check)
    else:
        assert validator_func(delay, positive_check=positive_check) == delay


@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
@pytest.mark.parametrize("validator_func", [validate_timeout_delay, validate_optional_timeout_delay])
def test____validate_timeout_delay____convert_integer_value(
    positive_check: bool,
    validator_func: _validate_timeout_delay_func_type,
) -> None:
    # Arrange
    delay: int = 32

    # Act
    new_delay = validator_func(delay, positive_check=positive_check)

    # Assert
    assert type(new_delay) is float
    assert new_delay == 32.0


@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
@pytest.mark.parametrize("validator_func", [validate_timeout_delay, validate_optional_timeout_delay])
def test____validate_timeout_delay____not_a_number(
    positive_check: bool,
    validator_func: _validate_timeout_delay_func_type,
) -> None:
    # Arrange
    delay: float = math.nan

    # Act & Assert
    with pytest.raises(ValueError, match=r"^Invalid delay: NaN \(not a number\)$"):
        validator_func(delay, positive_check=positive_check)


@pytest.mark.parametrize("positive_check", [False, True], ids=lambda positive_check: f"{positive_check=}")
def test____validate_optional_timeout_delay____None_value(positive_check: bool) -> None:
    # Arrange

    # Act & Assert
    assert validate_optional_timeout_delay(None, positive_check=positive_check) == math.inf


def test____iter_bytes____iterate_over_bytes_returning_one_byte() -> None:
    # Arrange
    to_split = b"abcd"
    expected_result = [b"a", b"b", b"c", b"d"]

    # Act
    result = list(iter_bytes(to_split))

    # Assert
    assert result == expected_result


def test____adjust_leftover_buffer____consume_whole_buffer() -> None:
    # Arrange
    buffers: deque[memoryview] = deque(map(lambda v: memoryview(v), [b"abc", b"de", b"fgh"]))

    # Act
    adjust_leftover_buffer(buffers, 8)

    # Assert
    assert not buffers


def test____adjust_leftover_buffer____remove_some_buffers() -> None:
    # Arrange
    buffers: deque[memoryview] = deque(map(lambda v: memoryview(v), [b"abc", b"de", b"fgh"]))

    # Act
    adjust_leftover_buffer(buffers, 5)

    # Assert
    assert list(buffers) == [b"fgh"]


def test____adjust_leftover_buffer____partial_buffer_remove() -> None:
    # Arrange
    buffers: deque[memoryview] = deque(map(lambda v: memoryview(v), [b"abc", b"de", b"fgh"]))

    # Act
    adjust_leftover_buffer(buffers, 4)

    # Assert
    assert list(buffers) == [b"e", b"fgh"]


def test____adjust_leftover_buffer____handle_view_with_different_item_sizes() -> None:
    # Arrange
    import array

    item = array.array("i", [56, 23, 45, -4])

    buffers: deque[memoryview] = deque([memoryview(item)])

    # Act
    adjust_leftover_buffer(buffers, item.itemsize * 2)

    # Assert
    assert list(buffers) == [bytes(item[2:])]


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


@pytest.mark.parametrize("host", ["", None], ids=repr)
def test____validate_listener_hosts____any_address(host: Literal[""] | None) -> None:
    # Arrange

    # Act
    host_list = validate_listener_hosts(host)

    # Assert
    assert host_list == [None]


def test____validate_listener_hosts____single_address() -> None:
    # Arrange

    # Act
    host_list = validate_listener_hosts("local_address")

    # Assert
    assert host_list == ["local_address"]


def test____validate_listener_hosts____sequence_of_addresses() -> None:
    # Arrange

    # Act
    host_list = validate_listener_hosts(["local_address_1", "local_address_2"])

    # Assert
    assert host_list == ["local_address_1", "local_address_2"]


def test____validate_listener_hosts____mix_is_forbidden() -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(TypeError):
        validate_listener_hosts(["local_address_1", None])  # type: ignore[list-item]


def test____convert_socket_bind_error____add_context_to_error() -> None:
    # Arrange
    addr = ("127.0.0.1", 12345)
    original_error = OSError(EADDRINUSE, os.strerror(EADDRINUSE))
    with pytest.raises(OSError):
        raise original_error
    assert original_error.__traceback__ is not None

    # Act
    new_error = convert_socket_bind_error(original_error, addr)

    # Assert
    assert new_error.errno == EADDRINUSE
    assert new_error.strerror == f"error while attempting to bind on address {addr!r}: {original_error.strerror}"
    assert new_error.__traceback__ is original_error.__traceback__

    ## Remove circular references
    original_error.__traceback__ = new_error.__traceback__ = None


def test____convert_socket_bind_error____add_context_to_error____without_errno() -> None:
    # Arrange
    addr = "/path/to/unix.sock"
    original_error = OSError("AF_UNIX path too long.")  # <- Thanks CPython :)
    with pytest.raises(OSError):
        raise original_error
    assert original_error.__traceback__ is not None

    # Act
    new_error = convert_socket_bind_error(original_error, addr)

    # Assert
    assert new_error.errno == EINVAL
    assert new_error.strerror == f"error while attempting to bind on address {addr!r}: AF_UNIX path too long."
    assert new_error.__traceback__ is original_error.__traceback__

    ## Remove circular references
    original_error.__traceback__ = new_error.__traceback__ = None


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


def test____iterate_exceptions____yield_exception() -> None:
    # Arrange
    exception = BaseException()

    # Act
    all_exceptions = list(iterate_exceptions(exception))

    # Assert
    assert all_exceptions == [exception]


def test____iterate_exceptions____yield_exceptions_in_group() -> None:
    # Arrange
    excgrp = BaseExceptionGroup("", [BaseException(), Exception()])

    # Act
    all_exceptions = list(iterate_exceptions(excgrp))

    # Assert
    assert all_exceptions == list(excgrp.exceptions)


def test____iterate_exceptions____recursive_yield_exceptions_in_group() -> None:
    # Arrange
    sub_excgrp1 = BaseExceptionGroup("", [BaseException(), Exception()])
    sub_excgrp2 = BaseExceptionGroup("", [BaseException(), Exception()])

    # Act
    all_exceptions = list(iterate_exceptions(BaseExceptionGroup("", [sub_excgrp1, sub_excgrp2])))

    # Assert
    assert all_exceptions == list(itertools.chain(sub_excgrp1.exceptions, sub_excgrp2.exceptions))


def test____Flag___set_and_reset() -> None:
    # Arrange
    flag = Flag()
    assert not flag.is_set()

    # Act & Assert
    flag.set()
    assert flag.is_set()
    flag.set()
    assert flag.is_set()
    flag.clear()
    assert not flag.is_set()
    flag.clear()
    assert not flag.is_set()


def test____ElapsedTime____catch_elapsed_time(mocker: MockerFixture) -> None:
    # Arrange
    now: float = 798546132.0
    mocker.patch("time.perf_counter", autospec=True, side_effect=[now, now + 12.0])

    # Act
    with ElapsedTime() as elapsed:
        pass

    # Assert
    assert elapsed.get_elapsed() == pytest.approx(12.0)
    assert elapsed.recompute_timeout(42.4) == pytest.approx(30.4)
    assert elapsed.recompute_timeout(8.0) == 0.0


def test____ElapsedTime____not_reentrant() -> None:
    # Arrange
    with ElapsedTime() as elapsed:
        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^Already entered$"):
            with elapsed:
                pytest.fail("Should not enter")


def test____ElapsedTime____double_exit() -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(RuntimeError, match=r"^Already exited$"):
        with contextlib.ExitStack() as stack:
            elapsed = stack.enter_context(ElapsedTime())
            stack.push(elapsed)


def test____ElapsedTime____get_elapsed____not_entered() -> None:
    # Arrange
    elapsed = ElapsedTime()

    # Act & Assert
    with pytest.raises(RuntimeError, match=r"^Not entered$"):
        elapsed.get_elapsed()


def test____ElapsedTime____get_elapsed____within_context() -> None:
    # Arrange

    # Act & Assert
    with ElapsedTime() as elapsed:
        with pytest.raises(RuntimeError, match=r"^Within context$"):
            elapsed.get_elapsed()


def test____lock_with_timeout____acquire_and_release_with_timeout_at_None() -> None:
    # Arrange
    lock = threading.Lock()

    # Act & Assert
    assert not lock.locked()
    with lock_with_timeout(lock, None) as timeout:
        assert timeout is None
        assert lock.locked()
    assert not lock.locked()


def test____lock_with_timeout____acquire_and_release_with_timeout_at_infinite() -> None:
    # Arrange
    lock = threading.Lock()

    # Act & Assert
    assert not lock.locked()
    with lock_with_timeout(lock, math.inf) as timeout:
        assert timeout is math.inf
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


@runtime_final_class
class Klass:
    pass


def test____runtime_final_class____forgive_subclassing() -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(TypeError, match=r"^Klass cannot be subclassed$"):

        class Test(Klass):
            pass

        del Test
