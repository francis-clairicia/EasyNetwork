from __future__ import annotations

import contextlib
import logging
import traceback
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._utils import remove_traceback_frames_in_place
from easynetwork.lowlevel.request_handler import RecvParams
from easynetwork.servers.handlers import (
    AsyncDatagramClient,
    AsyncDatagramRequestHandler,
    AsyncStreamClient,
    AsyncStreamRequestHandler,
)
from easynetwork.servers.misc import build_lowlevel_datagram_server_handler, build_lowlevel_stream_server_handler

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class _DummyStreamRequestHandler(AsyncStreamRequestHandler[Any, Any]):
    def __init__(self, max_nb_yields: int, *, client_disconnect_stub: MagicMock | None = None) -> None:
        self._max_nb_yields: int = max_nb_yields
        self._client_disconnect_stub: MagicMock | None = client_disconnect_stub
        assert self._max_nb_yields >= 0

    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[RecvParams, Any]:
        if self._max_nb_yields < 1:
            return
        for _ in range(self._max_nb_yields):
            try:
                data = yield RecvParams(timeout=1234567.89)
            except GeneratorExit:
                await client.send_packet("generator exit")
                raise
            except Exception as exc:
                await client.send_packet(f"exception caught: {type(exc).__name__}: {exc}")
            else:
                if data == "__raise_error__":
                    raise RuntimeError("test")
                await client.send_packet(data)
        await client.aclose()

    async def on_disconnection(self, client: AsyncStreamClient[Any]) -> None:
        if self._client_disconnect_stub is not None:
            self._client_disconnect_stub(client, is_closing=client.is_closing())


class _DummyStreamRequestHandlerRepeat(_DummyStreamRequestHandler):

    def __init__(self, *, should_yield: bool = True, client_disconnect_stub: MagicMock | None = None) -> None:
        super().__init__(max_nb_yields=1 if should_yield else 0, client_disconnect_stub=client_disconnect_stub)
        self.close_handler_at_end: bool = False

    async def handle(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[RecvParams, Any]:
        if self._max_nb_yields == 0:
            return
        assert self._max_nb_yields == 1
        try:
            try:
                data = yield RecvParams(timeout=1234567.89)
            except GeneratorExit:
                await client.send_packet("generator exit")
                raise
            except Exception as exc:
                await client.send_packet(f"exception caught: {type(exc).__name__}: {exc}")
            else:
                if data == "__raise_error__":
                    raise RuntimeError("test")
                await client.send_packet(data)
        finally:
            if self.close_handler_at_end:
                await client.aclose()


class _DummyStreamRequestHandlerCoroutineConnection(_DummyStreamRequestHandler):

    async def on_connection(self, client: AsyncStreamClient[Any]) -> None:
        await client.send_packet("connection OK")


class _DummyStreamRequestHandlerAsyncGenConnection(_DummyStreamRequestHandler):

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

    async def on_connection(self, client: AsyncStreamClient[Any]) -> AsyncGenerator[RecvParams, Any]:
        if self._max_nb_connection_hook_yields < 1:
            await client.send_packet("connection OK without yield")
            return
        for i in range(self._max_nb_connection_hook_yields):
            i += 1
            try:
                data = yield RecvParams(timeout=4000 + i)
            except GeneratorExit:
                await client.send_packet("generator exit from on_connection hook")
                raise
            except Exception as exc:
                await client.send_packet(f"exception caught in on_connection hook: {type(exc).__name__}: {exc}")
            else:
                if data == "__raise_error__":
                    raise RuntimeError("test")
                assert data == f"test connection {i}"
                await client.send_packet(f"connection OK {i}")


class _DummyDatagramRequestHandler(AsyncDatagramRequestHandler[Any, Any]):
    def __init__(self, max_nb_yields: int) -> None:
        self._max_nb_yields: int = max_nb_yields

    async def handle(self, client: AsyncDatagramClient[Any]) -> AsyncGenerator[RecvParams, Any]:
        for _ in range(self._max_nb_yields):
            try:
                data = yield RecvParams(timeout=1234567.89)
            except GeneratorExit:
                await client.send_packet("generator exit")
                raise
            except Exception as exc:
                await client.send_packet(f"exception caught: {type(exc).__name__}: {exc}")
            else:
                if data == "__raise_error__":
                    raise RuntimeError("test")
                await client.send_packet(data)


@pytest.mark.asyncio
async def test____build_lowlevel_datagram_server_handler____defer_yields(
    mock_async_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_datagram_client

    handler = build_lowlevel_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = await generator.asend(getattr(mocker.sentinel, f"data_{i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopAsyncIteration):
        await generator.asend(mocker.sentinel.data_5)

    # Assert
    assert mock_async_datagram_client.send_packet.await_args_list == [
        mocker.call(getattr(mocker.sentinel, f"data_{i + 1}")) for i in range(5)
    ]


@pytest.mark.asyncio
async def test____build_lowlevel_datagram_server_handler____no_yield(
    mock_async_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_datagram_client

    handler = build_lowlevel_datagram_server_handler(initializer, _DummyDatagramRequestHandler(0))

    # Act
    with pytest.raises(StopAsyncIteration):
        await anext(handler(mocker.sentinel.ctx))

    # Assert
    mock_async_datagram_client.send_packet.assert_not_called()


@pytest.mark.asyncio
async def test____build_lowlevel_datagram_server_handler____yield_None(
    mock_async_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_datagram_client

    handler = build_lowlevel_datagram_server_handler(initializer, _DummyDatagramRequestHandler(1))

    # Act
    await anext(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(StopAsyncIteration):
        await generator.asend(None)

    # Assert
    mock_async_datagram_client.send_packet.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test____build_lowlevel_datagram_server_handler____generator_close(
    mock_async_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_datagram_client

    handler = build_lowlevel_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act
    await anext(generator := handler(mocker.sentinel.ctx))
    await generator.aclose()

    # Assert
    mock_async_datagram_client.send_packet.assert_awaited_once_with("generator exit")


@pytest.mark.asyncio
async def test____build_lowlevel_datagram_server_handler____caught_exception(
    mock_async_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(Exception):
        pass

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_datagram_client

    handler = build_lowlevel_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = await generator.athrow(MyException(f"error {i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopAsyncIteration):
        await generator.athrow(MyException("error 5"))

    # Assert
    assert mock_async_datagram_client.send_packet.await_args_list == [
        mocker.call(f"exception caught: MyException: error {i + 1}") for i in range(5)
    ]


@pytest.mark.asyncio
async def test____build_lowlevel_datagram_server_handler____uncaught_exception(
    mock_async_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(BaseException):
        pass

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        try:
            yield mock_async_datagram_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: MyException) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("handle", "data = yield RecvParams(timeout=1234567.89)")]

    handler = build_lowlevel_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act & Assert
    await anext(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(MyException, check=check_exception_traceback):
        await generator.athrow(MyException("error"))


@pytest.mark.asyncio
async def test____build_lowlevel_datagram_server_handler____uncaught_exception____raised_by_request_handler(
    mock_async_datagram_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        try:
            yield mock_async_datagram_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: RuntimeError) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("handle", """raise RuntimeError("test")""")]

    handler = build_lowlevel_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act & Assert
    await anext(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(RuntimeError, check=check_exception_traceback):
        await generator.asend("__raise_error__")


@pytest.mark.asyncio
async def test____build_lowlevel_datagram_server_handler____skip_initialization(mocker: MockerFixture) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[None]:
        yield

    handler = build_lowlevel_datagram_server_handler(initializer, _DummyDatagramRequestHandler(5))

    # Act & Assert
    generator = handler(mocker.sentinel.ctx)
    with pytest.raises(StopAsyncIteration):
        await anext(generator)


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____defer_yields(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    handler = build_lowlevel_stream_server_handler(initializer, _DummyStreamRequestHandler(5))

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = await generator.asend(getattr(mocker.sentinel, f"data_{i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopAsyncIteration):
        await generator.asend(mocker.sentinel.data_5)

    # Assert
    assert mock_async_stream_client.send_packet.await_args_list == [
        mocker.call(getattr(mocker.sentinel, f"data_{i + 1}")) for i in range(5)
    ]


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____defer_yields____repeat_generator_until_close(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    request_handler = _DummyStreamRequestHandlerRepeat()
    handler = build_lowlevel_stream_server_handler(initializer, request_handler)

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = await generator.asend(getattr(mocker.sentinel, f"data_{i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    request_handler.close_handler_at_end = True
    with pytest.raises(StopAsyncIteration):
        await generator.asend(mocker.sentinel.data_5)

    # Assert
    assert mock_async_stream_client.send_packet.await_args_list == [
        mocker.call(getattr(mocker.sentinel, f"data_{i + 1}")) for i in range(5)
    ]


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____no_yield(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        _DummyStreamRequestHandler(0, client_disconnect_stub=client_disconnected_stub),
    )

    # Act
    with pytest.raises(StopAsyncIteration):
        await anext(handler(mocker.sentinel.ctx))

    # Assert
    mock_async_stream_client.send_packet.assert_not_called()
    mock_async_stream_client.aclose.assert_awaited_once_with()
    client_disconnected_stub.assert_called_once_with(mock_async_stream_client, is_closing=True)


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____no_yield____repeat_mode_closes_client(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerRepeat(should_yield=False, client_disconnect_stub=client_disconnected_stub),
    )

    # Act
    with pytest.raises(StopAsyncIteration):
        await anext(handler(mocker.sentinel.ctx))

    # Assert
    mock_async_stream_client.send_packet.assert_not_called()
    mock_async_stream_client.aclose.assert_awaited_once_with()
    client_disconnected_stub.assert_called_once_with(mock_async_stream_client, is_closing=True)


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____yield_None(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    handler = build_lowlevel_stream_server_handler(initializer, _DummyStreamRequestHandler(1))

    # Act
    await anext(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(StopAsyncIteration):
        await generator.asend(None)

    # Assert
    mock_async_stream_client.send_packet.assert_awaited_once_with(None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repeat_mode",
    [
        pytest.param(False, id="closing"),
        pytest.param(True, id="repeat"),
    ],
)
async def test____build_lowlevel_stream_server_handler____generator_close(
    repeat_mode: bool,
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        (
            _DummyStreamRequestHandlerRepeat(client_disconnect_stub=client_disconnected_stub)
            if repeat_mode
            else _DummyStreamRequestHandler(5, client_disconnect_stub=client_disconnected_stub)
        ),
    )

    # Act
    await anext(generator := handler(mocker.sentinel.ctx))
    await generator.aclose()

    # Assert
    mock_async_stream_client.send_packet.assert_awaited_once_with("generator exit")
    mock_async_stream_client.aclose.assert_not_called()
    client_disconnected_stub.assert_called_once_with(mock_async_stream_client, is_closing=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repeat_mode",
    [
        pytest.param(False, id="closing"),
        pytest.param(True, id="repeat"),
    ],
)
async def test____build_lowlevel_stream_server_handler____caught_exception(
    repeat_mode: bool,
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(Exception):
        pass

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    request_handler = (
        _DummyStreamRequestHandlerRepeat(client_disconnect_stub=client_disconnected_stub)
        if repeat_mode
        else _DummyStreamRequestHandler(5, client_disconnect_stub=client_disconnected_stub)
    )
    handler = build_lowlevel_stream_server_handler(initializer, request_handler)

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    for i in range(4):
        recv_params = await generator.athrow(MyException(f"error {i + 1}"))
        assert recv_params == RecvParams(timeout=1234567.89)
    if isinstance(request_handler, _DummyStreamRequestHandlerRepeat):
        request_handler.close_handler_at_end = True
    with pytest.raises(StopAsyncIteration):
        await generator.athrow(MyException("error 5"))

    # Assert
    assert mock_async_stream_client.send_packet.await_args_list == [
        mocker.call(f"exception caught: MyException: error {i + 1}") for i in range(5)
    ]
    client_disconnected_stub.assert_called_once_with(mock_async_stream_client, is_closing=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repeat_mode",
    [
        pytest.param(False, id="closing"),
        pytest.param(True, id="repeat"),
    ],
)
async def test____build_lowlevel_stream_server_handler____uncaught_exception(
    repeat_mode: bool,
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(BaseException):
        pass

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        try:
            yield mock_async_stream_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: MyException) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("handle", "data = yield RecvParams(timeout=1234567.89)")]

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        (
            _DummyStreamRequestHandlerRepeat(client_disconnect_stub=client_disconnected_stub)
            if repeat_mode
            else _DummyStreamRequestHandler(5, client_disconnect_stub=client_disconnected_stub)
        ),
    )

    # Act & Assert
    await anext(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(MyException, check=check_exception_traceback):
        await generator.athrow(MyException("error"))
    mock_async_stream_client.aclose.assert_not_called()
    client_disconnected_stub.assert_called_once_with(mock_async_stream_client, is_closing=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repeat_mode",
    [
        pytest.param(False, id="closing"),
        pytest.param(True, id="repeat"),
    ],
)
async def test____build_lowlevel_stream_server_handler____uncaught_exception____raised_by_request_handler(
    repeat_mode: bool,
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        try:
            yield mock_async_stream_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: RuntimeError) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("handle", """raise RuntimeError("test")""")]

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        (
            _DummyStreamRequestHandlerRepeat(client_disconnect_stub=client_disconnected_stub)
            if repeat_mode
            else _DummyStreamRequestHandler(5, client_disconnect_stub=client_disconnected_stub)
        ),
    )

    # Act & Assert
    await anext(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(RuntimeError, check=check_exception_traceback):
        await generator.asend("__raise_error__")
    mock_async_stream_client.aclose.assert_not_called()
    client_disconnected_stub.assert_called_once_with(mock_async_stream_client, is_closing=False)


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____coroutine_connection_hook(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    handler = build_lowlevel_stream_server_handler(initializer, _DummyStreamRequestHandlerCoroutineConnection(1))

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopAsyncIteration):
        await generator.asend(mocker.sentinel.data_1)

    # Assert
    assert mock_async_stream_client.send_packet.await_args_list == [
        mocker.call("connection OK"),
        mocker.call(mocker.sentinel.data_1),
    ]


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____coroutine_connection_hook____uncaught_exception(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    class MyException(Exception):
        pass

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    request_handler = _DummyStreamRequestHandlerCoroutineConnection(1, client_disconnect_stub=client_disconnected_stub)
    mocker.patch.object(request_handler, "on_connection", side_effect=MyException)
    handler = build_lowlevel_stream_server_handler(initializer, request_handler)

    # Act
    with pytest.raises(MyException):
        await anext(handler(mocker.sentinel.ctx))

    # Assert
    mock_async_stream_client.aclose.assert_not_called()
    client_disconnected_stub.assert_not_called()


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____async_gen_connection_hook(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    handler = build_lowlevel_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerAsyncGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
        ),
    )

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    recv_params = await generator.asend("test connection 1")
    assert recv_params == RecvParams(timeout=4002)
    recv_params = await generator.asend("test connection 2")
    assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopAsyncIteration):
        await generator.asend(mocker.sentinel.data_1)

    # Assert
    assert mock_async_stream_client.send_packet.await_args_list == [
        mocker.call("connection OK 1"),
        mocker.call("connection OK 2"),
        mocker.call(mocker.sentinel.data_1),
    ]


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____async_gen_connection_hook____no_yield(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerAsyncGenConnection(
            max_nb_connection_hook_yields=0,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopAsyncIteration):
        await generator.asend(mocker.sentinel.data_1)

    # Assert
    assert mock_async_stream_client.send_packet.await_args_list == [
        mocker.call("connection OK without yield"),
        mocker.call(mocker.sentinel.data_1),
    ]
    client_disconnected_stub.assert_called_once_with(mock_async_stream_client, is_closing=True)


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____async_gen_connection_hook____generator_closed(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerAsyncGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    await generator.aclose()

    # Assert
    mock_async_stream_client.send_packet.assert_awaited_once_with("generator exit from on_connection hook")
    mock_async_stream_client.aclose.assert_not_called()
    client_disconnected_stub.assert_not_called()


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____async_gen_connection_hook____caught_exception(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(Exception):
        pass

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerAsyncGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    recv_params = await generator.athrow(MyException("error 1"))
    assert recv_params == RecvParams(timeout=4002)
    recv_params = await generator.athrow(MyException("error 2"))
    assert recv_params == RecvParams(timeout=1234567.89)
    with pytest.raises(StopAsyncIteration):
        await generator.asend(mocker.sentinel.data_1)

    # Assert
    assert mock_async_stream_client.send_packet.await_args_list == [
        mocker.call("exception caught in on_connection hook: MyException: error 1"),
        mocker.call("exception caught in on_connection hook: MyException: error 2"),
        mocker.call(mocker.sentinel.data_1),
    ]
    client_disconnected_stub.assert_called_once_with(mock_async_stream_client, is_closing=True)


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____async_gen_connection_hook____uncaught_exception(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    class MyException(BaseException):
        pass

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        try:
            yield mock_async_stream_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: MyException) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("on_connection", "data = yield RecvParams(timeout=4000 + i)")]

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerAsyncGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    with pytest.raises(MyException, check=check_exception_traceback):
        await generator.athrow(MyException("error"))

    # Assert
    mock_async_stream_client.send_packet.assert_not_called()
    mock_async_stream_client.aclose.assert_not_called()
    client_disconnected_stub.assert_not_called()


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____async_gen_connection_hook____uncaught_exception____raised_by_request_handler(
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        try:
            yield mock_async_stream_client
        except BaseException as exc:
            remove_traceback_frames_in_place(exc, 1)
            raise

    def check_exception_traceback(exc: RuntimeError) -> bool:
        frames = traceback.extract_tb(remove_traceback_frames_in_place(exc, 1).__traceback__)
        return [(f.name, f.line) for f in frames] == [("on_connection", """raise RuntimeError("test")""")]

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    handler = build_lowlevel_stream_server_handler(
        initializer,
        _DummyStreamRequestHandlerAsyncGenConnection(
            max_nb_connection_hook_yields=2,
            max_nb_handler_yields=1,
            client_disconnect_stub=client_disconnected_stub,
        ),
    )

    # Act
    recv_params = await anext(generator := handler(mocker.sentinel.ctx))
    assert recv_params == RecvParams(timeout=4001)
    with pytest.raises(RuntimeError, check=check_exception_traceback):
        await generator.asend("__raise_error__")

    # Assert
    mock_async_stream_client.send_packet.assert_not_called()
    mock_async_stream_client.aclose.assert_not_called()
    client_disconnected_stub.assert_not_called()


@pytest.mark.asyncio
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
async def test____build_lowlevel_stream_server_handler____disconnect_hook____connection_error(
    connection_error_in_exc_group: bool,
    custom_logger: bool,
    mock_async_stream_client: MagicMock,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    caplog.set_level(logging.WARNING)

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[Any]:
        yield mock_async_stream_client

    client_disconnected_stub = mocker.stub("client_disconnected_stub")
    client_disconnected_stub.side_effect = (
        ExceptionGroup("", [ConnectionAbortedError()]) if connection_error_in_exc_group else ConnectionAbortedError()
    )
    handler = build_lowlevel_stream_server_handler(
        initializer,
        _DummyStreamRequestHandler(1, client_disconnect_stub=client_disconnected_stub),
        logger=logging.getLogger(__name__) if custom_logger else None,
    )

    # Act & Assert
    await anext(generator := handler(mocker.sentinel.ctx))
    with pytest.raises(StopAsyncIteration):
        await generator.asend(mocker.sentinel.test)
    client_disconnected_stub.assert_called_once_with(mock_async_stream_client, is_closing=True)
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].name == (__name__ if custom_logger else build_lowlevel_stream_server_handler.__module__)
    assert caplog.records[0].exc_info is None
    assert caplog.records[0].getMessage() == "ConnectionError raised in request_handler.on_disconnection()"


@pytest.mark.asyncio
async def test____build_lowlevel_stream_server_handler____skip_initialization(mocker: MockerFixture) -> None:
    # Arrange

    @contextlib.asynccontextmanager
    async def initializer(_: Any) -> AsyncGenerator[None]:
        yield

    handler = build_lowlevel_stream_server_handler(initializer, _DummyStreamRequestHandler(5))

    # Act & Assert
    generator = handler(mocker.sentinel.ctx)
    with pytest.raises(StopAsyncIteration):
        await anext(generator)
