from __future__ import annotations

import contextlib
import inspect
import logging
import traceback
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._utils import remove_traceback_frames_in_place
from easynetwork.lowlevel.request_handler import RecvParams
from easynetwork.servers.handlers import (
    BlockingDatagramClient,
    BlockingDatagramRequestHandler,
    BlockingStreamClient,
    BlockingStreamRequestHandler,
)
from easynetwork.servers.misc import (
    build_lowlevel_blocking_datagram_server_handler,
    build_lowlevel_blocking_stream_server_handler,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class _DummyStreamRequestHandler(BlockingStreamRequestHandler[Any, Any]):
    def __init__(self, max_nb_yields: int, *, client_disconnect_stub: MagicMock | None = None) -> None:
        self._max_nb_yields: int = max_nb_yields
        self._client_disconnect_stub: MagicMock | None = client_disconnect_stub
        assert self._max_nb_yields >= 0

    def handle(self, client: BlockingStreamClient[Any]) -> Generator[RecvParams, Any]:
        if self._max_nb_yields < 1:
            return
        for _ in range(self._max_nb_yields):
            try:
                data = yield RecvParams(timeout=1234567.89)
            except GeneratorExit:
                client.send_packet("generator exit")
                raise
            except Exception as exc:
                client.send_packet(f"exception caught: {type(exc).__name__}: {exc}")
            else:
                if data == "__raise_error__":
                    raise RuntimeError("test")
                client.send_packet(data)
        client.close()

    def on_disconnection(self, client: BlockingStreamClient[Any]) -> None:
        if self._client_disconnect_stub is not None:
            self._client_disconnect_stub(client, is_closing=client.is_closing())


class _DummyStreamRequestHandlerRepeat(_DummyStreamRequestHandler):

    def __init__(self, *, should_yield: bool = True, client_disconnect_stub: MagicMock | None = None) -> None:
        super().__init__(max_nb_yields=1 if should_yield else 0, client_disconnect_stub=client_disconnect_stub)
        self.close_handler_at_end: bool = False

    def handle(self, client: BlockingStreamClient[Any]) -> Generator[RecvParams, Any]:
        if self._max_nb_yields == 0:
            return
        assert self._max_nb_yields == 1
        try:
            try:
                data = yield RecvParams(timeout=1234567.89)
            except GeneratorExit:
                client.send_packet("generator exit")
                raise
            except Exception as exc:
                client.send_packet(f"exception caught: {type(exc).__name__}: {exc}")
            else:
                if data == "__raise_error__":
                    raise RuntimeError("test")
                client.send_packet(data)
        finally:
            if self.close_handler_at_end:
                client.close()


class _DummyStreamRequestHandlerSimpleConnection(_DummyStreamRequestHandler):

    def on_connection(self, client: BlockingStreamClient[Any]) -> None:
        client.send_packet("connection OK")


class _DummyStreamRequestHandlerBlockingGenConnection(_DummyStreamRequestHandler):

    def __init__(
        self,
        *,
        max_nb_connection_hook_yields: int,
        max_nb_handler_yields: int,
        client_disconnect_stub: MagicMock | None = None,
    ) -> None:
        super().__init__(max_nb_handler_yields, client_disconnect_stub=client_disconnect_stub)
        self._max_nb_connection_hook_yields: int = max_nb_connection_hook_yields
        assert self._max_nb_connection_hook_yields >= 0

    def on_connection(self, client: BlockingStreamClient[Any]) -> Generator[RecvParams, Any]:
        if self._max_nb_connection_hook_yields < 1:
            client.send_packet("connection OK without yield")
            return
        for i in range(self._max_nb_connection_hook_yields):
            i += 1
            try:
                data = yield RecvParams(timeout=4000 + i)
            except GeneratorExit:
                client.send_packet("generator exit from on_connection hook")
                raise
            except Exception as exc:
                client.send_packet(f"exception caught in on_connection hook: {type(exc).__name__}: {exc}")
            else:
                if data == "__raise_error__":
                    raise RuntimeError("test")
                assert data == f"test connection {i}"
                client.send_packet(f"connection OK {i}")


class _DummyDatagramRequestHandler(BlockingDatagramRequestHandler[Any, Any]):
    def __init__(self, max_nb_yields: int) -> None:
        self._max_nb_yields: int = max_nb_yields

    def handle(self, client: BlockingDatagramClient[Any]) -> Generator[RecvParams, Any]:
        for _ in range(self._max_nb_yields):
            try:
                data = yield RecvParams(timeout=1234567.89)
            except GeneratorExit:
                client.send_packet("generator exit")
                raise
            except Exception as exc:
                client.send_packet(f"exception caught: {type(exc).__name__}: {exc}")
            else:
                if data == "__raise_error__":
                    raise RuntimeError("test")
                client.send_packet(data)


def test____build_lowlevel_blocking_datagram_server_handler____defer_yields(
    mock_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_datagram_client

    handler = build_lowlevel_blocking_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = generator.send(getattr(mocker.sentinel, f"data_{i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopIteration):
        generator.send(mocker.sentinel.data_5)

    # Assert
    assert mock_datagram_client.send_packet.mock_calls == [
        mocker.call(getattr(mocker.sentinel, f"data_{i + 1}")) for i in range(5)
    ]


def test____build_lowlevel_blocking_datagram_server_handler____no_yield(
    mock_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_datagram_client

    handler = build_lowlevel_blocking_datagram_server_handler(initializer, _DummyDatagramRequestHandler(0))

    # Act
    with pytest.raises(StopIteration):
        next(handler(mocker.sentinel.ctx))

    # Assert
    mock_datagram_client.send_packet.assert_not_called()


def test____build_lowlevel_blocking_datagram_server_handler____yield_None(
    mock_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_datagram_client

    handler = build_lowlevel_blocking_datagram_server_handler(initializer, _DummyDatagramRequestHandler(1))

    # Act
    next(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(StopIteration):
        generator.send(None)

    # Assert
    mock_datagram_client.send_packet.assert_called_once_with(None)


def test____build_lowlevel_blocking_datagram_server_handler____generator_close(
    mock_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_datagram_client

    handler = build_lowlevel_blocking_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act
    next(generator := handler(mocker.sentinel.ctx))
    generator.close()

    # Assert
    mock_datagram_client.send_packet.assert_called_once_with("generator exit")


def test____build_lowlevel_blocking_datagram_server_handler____caught_exception(
    mock_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(Exception):
        pass

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_datagram_client

    handler = build_lowlevel_blocking_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = generator.throw(MyException(f"error {i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopIteration):
        generator.throw(MyException("error 5"))

    # Assert
    assert mock_datagram_client.send_packet.mock_calls == [
        mocker.call(f"exception caught: MyException: error {i + 1}") for i in range(5)
    ]


def test____build_lowlevel_blocking_datagram_server_handler____uncaught_exception(
    mock_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(BaseException):
        pass

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        try:
            yield mock_datagram_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: MyException) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("handle", "data = yield RecvParams(timeout=1234567.89)")]

    handler = build_lowlevel_blocking_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act & Assert
    next(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(MyException, check=check_exception_traceback):
        generator.throw(MyException("error"))


def test____build_lowlevel_blocking_datagram_server_handler____uncaught_exception____raised_by_request_handler(
    mock_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        try:
            yield mock_datagram_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: RuntimeError) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("handle", """raise RuntimeError("test")""")]

    handler = build_lowlevel_blocking_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act & Assert
    next(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(RuntimeError, check=check_exception_traceback):
        generator.send("__raise_error__")


def test____build_lowlevel_blocking_datagram_server_handler____skip_initialization(mocker: MockerFixture) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[None]:
        yield

    handler = build_lowlevel_blocking_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act & Assert
    generator = handler(mocker.sentinel.ctx)
    with pytest.raises(StopIteration):
        next(generator)


def test____build_lowlevel_blocking_stream_server_handler____defer_yields(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    handler = build_lowlevel_blocking_stream_server_handler(initializer, _DummyStreamRequestHandler(5))

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = generator.send(getattr(mocker.sentinel, f"data_{i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopIteration):
        generator.send(mocker.sentinel.data_5)

    # Assert
    assert mock_stream_client.send_packet.mock_calls == [mocker.call(getattr(mocker.sentinel, f"data_{i + 1}")) for i in range(5)]
    mock_stream_client.abort.assert_not_called()


def test____build_lowlevel_blocking_stream_server_handler____defer_yields____repeat_generator_until_close(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    request_handler = _DummyStreamRequestHandlerRepeat()
    handler = build_lowlevel_blocking_stream_server_handler(initializer, request_handler)

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = generator.send(getattr(mocker.sentinel, f"data_{i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    request_handler.close_handler_at_end = True
    with pytest.raises(StopIteration):
        generator.send(mocker.sentinel.data_5)

    # Assert
    assert mock_stream_client.send_packet.mock_calls == [mocker.call(getattr(mocker.sentinel, f"data_{i + 1}")) for i in range(5)]
    mock_stream_client.abort.assert_not_called()


def test____build_lowlevel_blocking_stream_server_handler____no_yield(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        _DummyStreamRequestHandler(0, client_disconnect_stub=client_disconnected_stub),
    )

    # Act
    with pytest.raises(StopIteration):
        next(handler(mocker.sentinel.ctx))

    # Assert
    mock_stream_client.send_packet.assert_not_called()
    mock_stream_client.abort.assert_called_once_with()
    mock_stream_client.close.assert_not_called()
    client_disconnected_stub.assert_called_once_with(mock_stream_client, is_closing=True)


def test____build_lowlevel_blocking_stream_server_handler____no_yield____repeat_mode_closes_client(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerRepeat(should_yield=False, client_disconnect_stub=client_disconnected_stub),
    )

    # Act
    with pytest.raises(StopIteration):
        next(handler(mocker.sentinel.ctx))

    # Assert
    mock_stream_client.send_packet.assert_not_called()
    mock_stream_client.abort.assert_called_once_with()
    mock_stream_client.close.assert_not_called()
    client_disconnected_stub.assert_called_once_with(mock_stream_client, is_closing=True)


def test____build_lowlevel_blocking_stream_server_handler____yield_None(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    handler = build_lowlevel_blocking_stream_server_handler(initializer, _DummyStreamRequestHandler(1))

    # Act
    next(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(StopIteration):
        generator.send(None)

    # Assert
    mock_stream_client.send_packet.assert_called_once_with(None)
    mock_stream_client.abort.assert_not_called()


@pytest.mark.parametrize(
    "repeat_mode",
    [
        pytest.param(False, id="closing"),
        pytest.param(True, id="repeat"),
    ],
)
def test____build_lowlevel_blocking_stream_server_handler____generator_close(
    repeat_mode: bool,
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        (
            _DummyStreamRequestHandlerRepeat(client_disconnect_stub=client_disconnected_stub)
            if repeat_mode
            else _DummyStreamRequestHandler(5, client_disconnect_stub=client_disconnected_stub)
        ),
    )

    # Act
    next(generator := handler(mocker.sentinel.ctx))
    generator.close()

    # Assert
    mock_stream_client.send_packet.assert_called_once_with("generator exit")
    mock_stream_client.abort.assert_not_called()
    mock_stream_client.close.assert_not_called()
    client_disconnected_stub.assert_called_once_with(mock_stream_client, is_closing=False)


@pytest.mark.parametrize(
    "repeat_mode",
    [
        pytest.param(False, id="closing"),
        pytest.param(True, id="repeat"),
    ],
)
def test____build_lowlevel_blocking_stream_server_handler____caught_exception(
    repeat_mode: bool,
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(Exception):
        pass

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    request_handler = (
        _DummyStreamRequestHandlerRepeat(client_disconnect_stub=client_disconnected_stub)
        if repeat_mode
        else _DummyStreamRequestHandler(5, client_disconnect_stub=client_disconnected_stub)
    )
    handler = build_lowlevel_blocking_stream_server_handler(initializer, request_handler)

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = generator.throw(MyException(f"error {i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    if isinstance(request_handler, _DummyStreamRequestHandlerRepeat):
        request_handler.close_handler_at_end = True
    with pytest.raises(StopIteration):
        generator.throw(MyException("error 5"))

    # Assert
    assert mock_stream_client.send_packet.mock_calls == [
        mocker.call(f"exception caught: MyException: error {i + 1}") for i in range(5)
    ]
    mock_stream_client.abort.assert_not_called()
    client_disconnected_stub.assert_called_once_with(mock_stream_client, is_closing=True)


@pytest.mark.parametrize(
    "repeat_mode",
    [
        pytest.param(False, id="closing"),
        pytest.param(True, id="repeat"),
    ],
)
def test____build_lowlevel_blocking_stream_server_handler____uncaught_exception(
    repeat_mode: bool,
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(BaseException):
        pass

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        try:
            yield mock_stream_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: MyException) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("handle", "data = yield RecvParams(timeout=1234567.89)")]

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        (
            _DummyStreamRequestHandlerRepeat(client_disconnect_stub=client_disconnected_stub)
            if repeat_mode
            else _DummyStreamRequestHandler(5, client_disconnect_stub=client_disconnected_stub)
        ),
    )

    # Act & Assert
    next(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(MyException, check=check_exception_traceback):
        generator.throw(MyException("error"))
    mock_stream_client.abort.assert_not_called()
    mock_stream_client.close.assert_not_called()
    client_disconnected_stub.assert_called_once_with(mock_stream_client, is_closing=False)


@pytest.mark.parametrize(
    "repeat_mode",
    [
        pytest.param(False, id="closing"),
        pytest.param(True, id="repeat"),
    ],
)
def test____build_lowlevel_blocking_stream_server_handler____uncaught_exception____raised_by_request_handler(
    repeat_mode: bool,
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        try:
            yield mock_stream_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: RuntimeError) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("handle", """raise RuntimeError("test")""")]

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        (
            _DummyStreamRequestHandlerRepeat(client_disconnect_stub=client_disconnected_stub)
            if repeat_mode
            else _DummyStreamRequestHandler(5, client_disconnect_stub=client_disconnected_stub)
        ),
    )

    # Act & Assert
    next(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(RuntimeError, check=check_exception_traceback):
        generator.send("__raise_error__")
    mock_stream_client.abort.assert_not_called()
    mock_stream_client.close.assert_not_called()
    client_disconnected_stub.assert_called_once_with(mock_stream_client, is_closing=False)


def test____build_lowlevel_blocking_stream_server_handler____simple_connection_hook(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    handler = build_lowlevel_blocking_stream_server_handler(initializer, _DummyStreamRequestHandlerSimpleConnection(1))

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopIteration):
        generator.send(mocker.sentinel.data_1)

    # Assert
    assert mock_stream_client.send_packet.mock_calls == [
        mocker.call("connection OK"),
        mocker.call(mocker.sentinel.data_1),
    ]


def test____build_lowlevel_blocking_stream_server_handler____simple_connection_hook____uncaught_exception(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    class MyException(Exception):
        pass

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    request_handler = _DummyStreamRequestHandlerSimpleConnection(1, client_disconnect_stub=client_disconnected_stub)
    mocker.patch.object(request_handler, "on_connection", side_effect=MyException)
    handler = build_lowlevel_blocking_stream_server_handler(initializer, request_handler)

    # Act
    with pytest.raises(MyException):
        next(handler(mocker.sentinel.ctx))

    # Assert
    mock_stream_client.abort.assert_not_called()
    mock_stream_client.close.assert_not_called()
    client_disconnected_stub.assert_not_called()


def test____build_lowlevel_blocking_stream_server_handler____async_gen_connection_hook(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerBlockingGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
        ),
    )

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    recv_params = generator.send("test connection 1")
    assert recv_params == RecvParams(timeout=4002)
    recv_params = generator.send("test connection 2")
    assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopIteration):
        generator.send(mocker.sentinel.data_1)

    # Assert
    assert mock_stream_client.send_packet.mock_calls == [
        mocker.call("connection OK 1"),
        mocker.call("connection OK 2"),
        mocker.call(mocker.sentinel.data_1),
    ]


def test____build_lowlevel_blocking_stream_server_handler____async_gen_connection_hook____no_yield(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerBlockingGenConnection(
            max_nb_connection_hook_yields=0,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopIteration):
        generator.send(mocker.sentinel.data_1)

    # Assert
    assert mock_stream_client.send_packet.mock_calls == [
        mocker.call("connection OK without yield"),
        mocker.call(mocker.sentinel.data_1),
    ]
    client_disconnected_stub.assert_called_once_with(mock_stream_client, is_closing=True)


def test____build_lowlevel_blocking_stream_server_handler____async_gen_connection_hook____generator_closed(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerBlockingGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    generator.close()

    # Assert
    mock_stream_client.send_packet.assert_called_once_with("generator exit from on_connection hook")
    mock_stream_client.abort.assert_not_called()
    mock_stream_client.close.assert_not_called()
    client_disconnected_stub.assert_not_called()


def test____build_lowlevel_blocking_stream_server_handler____async_gen_connection_hook____caught_exception(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(Exception):
        pass

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerBlockingGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    recv_params = generator.throw(MyException("error 1"))
    assert recv_params == RecvParams(timeout=4002)
    recv_params = generator.throw(MyException("error 2"))
    assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopIteration):
        generator.send(mocker.sentinel.data_1)

    # Assert
    assert mock_stream_client.send_packet.mock_calls == [
        mocker.call("exception caught in on_connection hook: MyException: error 1"),
        mocker.call("exception caught in on_connection hook: MyException: error 2"),
        mocker.call(mocker.sentinel.data_1),
    ]
    client_disconnected_stub.assert_called_once_with(mock_stream_client, is_closing=True)


def test____build_lowlevel_blocking_stream_server_handler____async_gen_connection_hook____uncaught_exception(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(BaseException):
        pass

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        try:
            yield mock_stream_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: MyException) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("on_connection", "data = yield RecvParams(timeout=4000 + i)")]

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerBlockingGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    with pytest.raises(MyException, check=check_exception_traceback):
        generator.throw(MyException("error"))

    # Assert
    mock_stream_client.send_packet.assert_not_called()
    mock_stream_client.abort.assert_not_called()
    mock_stream_client.close.assert_not_called()
    client_disconnected_stub.assert_not_called()


def test____build_lowlevel_blocking_stream_server_handler____async_gen_connection_hook____uncaught_exception____raised_by_request_handler(
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        try:
            yield mock_stream_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: RuntimeError) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("on_connection", """raise RuntimeError("test")""")]

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerBlockingGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = next(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    with pytest.raises(RuntimeError, check=check_exception_traceback):
        generator.send("__raise_error__")

    # Assert
    mock_stream_client.send_packet.assert_not_called()
    mock_stream_client.abort.assert_not_called()
    mock_stream_client.close.assert_not_called()
    client_disconnected_stub.assert_not_called()


@pytest.mark.parametrize(
    "connection_error_in_exc_group",
    [
        pytest.param(False, id="bare_exception"),
        pytest.param(True, id="within_exception_group"),
    ],
)
@pytest.mark.parametrize(
    "custom_logger",
    [
        pytest.param(False, id="default_logger"),
        pytest.param(True, id="custom_logger"),
    ],
)
def test____build_lowlevel_blocking_stream_server_handler____disconnect_hook____connection_error(
    connection_error_in_exc_group: bool,
    custom_logger: bool,
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    caplog.set_level(logging.WARNING)

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    client_disconnected_stub.side_effect = (
        ExceptionGroup("", [ConnectionAbortedError()]) if connection_error_in_exc_group else ConnectionAbortedError()
    )
    handler = build_lowlevel_blocking_stream_server_handler(
        initializer,
        _DummyStreamRequestHandler(1, client_disconnect_stub=client_disconnected_stub),
        logger=logging.getLogger(__name__) if custom_logger else None,
    )

    # Act & Assert
    next(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(StopIteration):
        generator.send(mocker.sentinel.test)
    client_disconnected_stub.assert_called_once_with(mock_stream_client, is_closing=True)
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].name == (__name__ if custom_logger else build_lowlevel_blocking_stream_server_handler.__module__)
    assert caplog.records[0].exc_info is None
    assert caplog.records[0].getMessage() == "ConnectionError raised in request_handler.on_disconnection()"


def test____build_lowlevel_blocking_stream_server_handler____skip_initialization(mocker: MockerFixture) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[None]:
        yield

    handler = build_lowlevel_blocking_stream_server_handler(initializer, _DummyStreamRequestHandler(5))

    # Act & Assert
    generator = handler(mocker.sentinel.ctx)
    with pytest.raises(StopIteration):
        next(generator)


def test____build_lowlevel_blocking_stream_server_handler____fix_subgenerator_introspection(
    request: pytest.FixtureRequest,
    mock_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.contextmanager
    def initializer(_: Any) -> Generator[Any]:
        yield mock_stream_client

    handler = build_lowlevel_blocking_stream_server_handler(initializer, _DummyStreamRequestHandler(5))

    # Act
    next(generator := handler(mocker.sentinel.ctx))
    request.addfinalizer(generator.close)
    gi_yieldfrom = getattr(generator, "gi_yieldfrom")

    # Assert
    assert isinstance(gi_yieldfrom, Generator)
    assert inspect.getgeneratorstate(gi_yieldfrom) == "GEN_SUSPENDED"
